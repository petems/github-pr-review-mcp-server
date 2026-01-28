"""MCP JSON-RPC transport implementation.

This module implements the MCP Streaming HTTP transport protocol (spec: 2025-03-26).
It handles:
- Session management
- JSON-RPC message parsing and routing
- Protocol handshakes (initialize)
- Tool execution dispatching
"""

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from .server import PRReviewServer

logger = logging.getLogger(__name__)


# JSON-RPC Error Codes (from spec)
JSONRPC_PARSE_ERROR = -32700
JSONRPC_INVALID_REQUEST = -32600
JSONRPC_METHOD_NOT_FOUND = -32601
JSONRPC_INVALID_PARAMS = -32602
JSONRPC_INTERNAL_ERROR = -32603


@dataclass
class MCPSession:
    """Represents an active MCP session.

    Each session tracks:
    - Authentication credentials
    - Initialization state
    - Client capabilities
    - Activity timestamps for expiry
    """

    session_id: str
    mcp_key: str
    github_token: str
    initialized: bool = False
    client_info: dict[str, Any] = field(default_factory=dict)
    capabilities: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.utcnow)
    last_activity: datetime = field(default_factory=datetime.utcnow)


class MCPSessionStore:
    """In-memory storage for MCP sessions.

    Provides:
    - Session creation and retrieval
    - Activity tracking
    - Automatic cleanup of expired sessions
    """

    def __init__(self) -> None:
        """Initialize empty session store."""
        self._sessions: dict[str, MCPSession] = {}
        self._lock = asyncio.Lock()

    async def create_session(self, mcp_key: str, github_token: str) -> MCPSession:
        """Create a new MCP session.

        Args:
            mcp_key: Authentication key for MCP access
            github_token: GitHub API token for this session

        Returns:
            New MCPSession with unique session_id
        """
        async with self._lock:
            session_id = str(uuid.uuid4())
            session = MCPSession(
                session_id=session_id,
                mcp_key=mcp_key,
                github_token=github_token,
            )
            self._sessions[session_id] = session
            logger.info(f"Created MCP session: {session_id}")
            return session

    async def get_session(self, session_id: str) -> MCPSession | None:
        """Retrieve session by ID.

        Args:
            session_id: Session identifier

        Returns:
            MCPSession if found, None otherwise
        """
        async with self._lock:
            return self._sessions.get(session_id)

    async def update_activity(self, session_id: str) -> None:
        """Update last activity timestamp for session.

        Args:
            session_id: Session identifier
        """
        async with self._lock:
            session = self._sessions.get(session_id)
            if session:
                session.last_activity = datetime.utcnow()

    async def delete_session(self, session_id: str) -> bool:
        """Delete a session.

        Args:
            session_id: Session identifier

        Returns:
            True if session was deleted, False if not found
        """
        async with self._lock:
            if session_id in self._sessions:
                del self._sessions[session_id]
                logger.info(f"Deleted MCP session: {session_id}")
                return True
            return False

    async def cleanup_expired(self, max_age_seconds: int = 3600) -> int:
        """Remove sessions older than max_age_seconds.

        Args:
            max_age_seconds: Maximum age in seconds before expiry

        Returns:
            Number of sessions cleaned up
        """
        async with self._lock:
            now = datetime.utcnow()
            expired = [
                sid
                for sid, session in self._sessions.items()
                if (now - session.last_activity).total_seconds() > max_age_seconds
            ]

            for sid in expired:
                del self._sessions[sid]
                logger.debug(f"Expired MCP session: {sid}")

            return len(expired)


class MCPMessageHandler:
    """Handles MCP JSON-RPC message processing.

    Routes messages to appropriate handlers:
    - initialize: Protocol handshake
    - tools/list: Tool discovery
    - tools/call: Tool execution
    """

    def __init__(self, pr_review_server: PRReviewServer) -> None:
        """Initialize message handler.

        Args:
            pr_review_server: PRReviewServer instance for tool execution
        """
        self.pr_review_server = pr_review_server

    async def handle_message(
        self, session: MCPSession | None, message: dict[str, Any]
    ) -> dict[str, Any] | None:
        """Process a JSON-RPC message and return response.

        Args:
            session: Current MCP session (None for initialize)
            message: JSON-RPC message dict

        Returns:
            JSON-RPC response dict, or None for notifications
        """
        # Extract method and params
        # (mypy note: we trust the caller to pass dict, runtime check is defensive)
        method = message.get("method")
        msg_id = message.get("id")
        params = message.get("params", {})

        # Notifications have no response
        if is_notification(message):
            logger.debug(f"Received notification: {method}")
            return None

        # Handle request
        if not method:
            return create_jsonrpc_error(
                msg_id, JSONRPC_INVALID_REQUEST, "Missing 'method' field"
            )

        try:
            # Route to handler
            if method == "initialize":
                result = await self._handle_initialize(session, params)
            elif method == "tools/list":
                result = await self._handle_tools_list(session)
            elif method == "tools/call":
                result = await self._handle_tools_call(session, params)
            else:
                return create_jsonrpc_error(
                    msg_id, JSONRPC_METHOD_NOT_FOUND, f"Unknown method: {method}"
                )

            return create_jsonrpc_response(msg_id, result)

        except Exception as e:
            logger.exception(f"Error handling method {method}")
            return create_jsonrpc_error(
                msg_id, JSONRPC_INTERNAL_ERROR, f"Internal error: {e!s}"
            )

    async def _handle_initialize(
        self, session: MCPSession | None, params: dict[str, Any]
    ) -> dict[str, Any]:
        """Handle initialize request.

        Args:
            session: Session (should be None for initialize)
            params: Initialize parameters

        Returns:
            Initialize result with protocol version and capabilities
        """
        # Extract client info
        protocol_version = params.get("protocolVersion", "2025-03-26")
        client_info = params.get("clientInfo", {})

        logger.info(
            f"Initialize request - client: {client_info.get('name', 'unknown')}, "
            f"protocol: {protocol_version}"
        )

        # Build response
        result = {
            "protocolVersion": "2025-03-26",
            "capabilities": {
                "tools": {
                    "listChanged": False
                },  # We don't support dynamic tool changes
            },
            "serverInfo": {
                "name": "github-pr-review",
                "version": getattr(self.pr_review_server, "__version__", "0.1.0"),
            },
        }

        # Mark session as initialized if we have one
        # (Note: session creation happens in http_server.py after this returns)

        return result

    async def _handle_tools_list(self, session: MCPSession | None) -> dict[str, Any]:
        """Handle tools/list request.

        Args:
            session: Current session

        Returns:
            Tools list result
        """
        if not session or not session.initialized:
            raise ValueError("Session not initialized")

        # Call existing handle_list_tools
        tools = await self.pr_review_server.handle_list_tools()

        # Convert to MCP format
        return {"tools": [tool.model_dump() for tool in tools]}

    async def _handle_tools_call(
        self, session: MCPSession | None, params: dict[str, Any]
    ) -> dict[str, Any]:
        """Handle tools/call request.

        Args:
            session: Current session
            params: Tool call parameters (name, arguments)

        Returns:
            Tool call result
        """
        if not session or not session.initialized:
            raise ValueError("Session not initialized")

        tool_name = params.get("name")
        arguments = params.get("arguments", {})

        if not tool_name:
            raise ValueError("Missing 'name' parameter")

        # Add github_token to arguments for tool execution
        arguments["github_token"] = session.github_token

        # Call existing handle_call_tool
        result = await self.pr_review_server.handle_call_tool(tool_name, arguments)

        # Convert to MCP format
        return {
            "content": [{"type": "text", "text": content.text} for content in result]
        }


# JSON-RPC Helper Functions


def parse_jsonrpc_message(body: dict[str, Any]) -> tuple[str | None, dict[str, Any]]:
    """Extract method and params from JSON-RPC message.

    Args:
        body: JSON-RPC message dict

    Returns:
        Tuple of (method, params)
    """
    method = body.get("method")
    params = body.get("params", {})
    return method, params


def create_jsonrpc_response(msg_id: int | str | None, result: Any) -> dict[str, Any]:
    """Create JSON-RPC success response.

    Args:
        msg_id: Message ID from request
        result: Result value

    Returns:
        JSON-RPC response dict
    """
    return {"jsonrpc": "2.0", "id": msg_id, "result": result}


def create_jsonrpc_error(
    msg_id: int | str | None, code: int, message: str, data: Any = None
) -> dict[str, Any]:
    """Create JSON-RPC error response.

    Args:
        msg_id: Message ID from request (None for parse errors)
        code: Error code (e.g., -32600 for invalid request)
        message: Error message
        data: Optional additional error data

    Returns:
        JSON-RPC error response dict
    """
    error = {"code": code, "message": message}
    if data is not None:
        error["data"] = data

    return {"jsonrpc": "2.0", "id": msg_id, "error": error}


def is_request(message: dict[str, Any]) -> bool:
    """Check if message is a JSON-RPC request.

    Requests have both 'method' and 'id' fields.

    Args:
        message: JSON-RPC message

    Returns:
        True if message is a request
    """
    return "method" in message and "id" in message


def is_notification(message: dict[str, Any]) -> bool:
    """Check if message is a JSON-RPC notification.

    Notifications have 'method' but no 'id'.

    Args:
        message: JSON-RPC message

    Returns:
        True if message is a notification
    """
    return "method" in message and "id" not in message


def is_response(message: dict[str, Any]) -> bool:
    """Check if message is a JSON-RPC response.

    Responses have 'result' or 'error' and 'id'.

    Args:
        message: JSON-RPC message

    Returns:
        True if message is a response
    """
    return ("result" in message or "error" in message) and "id" in message
