"""Unit tests for MCP transport layer.

Tests session management, JSON-RPC message handling, and protocol helpers.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from mcp_github_pr_review.mcp_transport import (
    JSONRPC_INTERNAL_ERROR,
    JSONRPC_INVALID_REQUEST,
    JSONRPC_METHOD_NOT_FOUND,
    MCPMessageHandler,
    MCPSession,
    MCPSessionStore,
    create_jsonrpc_error,
    create_jsonrpc_response,
    is_notification,
    is_request,
    is_response,
    parse_jsonrpc_message,
)

# =====================================================================
# Test MCPSession
# =====================================================================


class TestMCPSession:
    """Test session data structure."""

    def test_create_session(self) -> None:
        """Test creating a session."""
        session = MCPSession(
            session_id="test-123",
            mcp_key="key-abc",
            github_token="ghp_test",  # noqa: S106
        )

        assert session.session_id == "test-123"
        assert session.mcp_key == "key-abc"
        assert session.github_token == "ghp_test"  # noqa: S105
        assert not session.initialized
        assert session.client_info == {}
        assert session.capabilities == {}

    def test_session_with_data(self) -> None:
        """Test session with client info and capabilities."""
        session = MCPSession(
            session_id="test-123",
            mcp_key="key-abc",
            github_token="ghp_test",  # noqa: S106
            initialized=True,
            client_info={"name": "test-client", "version": "1.0"},
            capabilities={"tools": True},
        )

        assert session.initialized
        assert session.client_info["name"] == "test-client"
        assert session.capabilities["tools"] is True


# =====================================================================
# Test MCPSessionStore
# =====================================================================


class TestMCPSessionStore:
    """Test session storage."""

    @pytest.mark.asyncio
    async def test_create_session(self) -> None:
        """Test creating and storing a session."""
        store = MCPSessionStore()

        session = await store.create_session("key-abc", "ghp_test")  # noqa: S106

        assert session.session_id is not None
        assert session.mcp_key == "key-abc"
        assert session.github_token == "ghp_test"  # noqa: S105

    @pytest.mark.asyncio
    async def test_get_session(self) -> None:
        """Test retrieving a session."""
        store = MCPSessionStore()

        # Create session
        created = await store.create_session("key-abc", "ghp_test")

        # Retrieve it
        retrieved = await store.get_session(created.session_id)

        assert retrieved is not None
        assert retrieved.session_id == created.session_id
        assert retrieved.mcp_key == "key-abc"

    @pytest.mark.asyncio
    async def test_get_nonexistent_session(self) -> None:
        """Test retrieving a session that doesn't exist."""
        store = MCPSessionStore()

        session = await store.get_session("nonexistent")

        assert session is None

    @pytest.mark.asyncio
    async def test_update_activity(self) -> None:
        """Test updating session activity timestamp."""
        store = MCPSessionStore()

        session = await store.create_session("key-abc", "ghp_test")
        original_activity = session.last_activity

        # Wait a bit
        await asyncio.sleep(0.1)

        # Update activity
        await store.update_activity(session.session_id)

        # Check timestamp changed
        updated = await store.get_session(session.session_id)
        assert updated is not None
        assert updated.last_activity > original_activity

    @pytest.mark.asyncio
    async def test_delete_session(self) -> None:
        """Test deleting a session."""
        store = MCPSessionStore()

        session = await store.create_session("key-abc", "ghp_test")

        # Delete it
        deleted = await store.delete_session(session.session_id)
        assert deleted is True

        # Verify it's gone
        retrieved = await store.get_session(session.session_id)
        assert retrieved is None

    @pytest.mark.asyncio
    async def test_delete_nonexistent_session(self) -> None:
        """Test deleting a session that doesn't exist."""
        store = MCPSessionStore()

        deleted = await store.delete_session("nonexistent")
        assert deleted is False

    @pytest.mark.asyncio
    async def test_cleanup_expired(self) -> None:
        """Test cleaning up expired sessions."""
        store = MCPSessionStore()

        # Create a session
        session = await store.create_session("key-abc", "ghp_test")

        # Manually set old activity time
        session.last_activity = session.last_activity.replace(year=2020)

        # Cleanup with 1 second max age
        count = await store.cleanup_expired(max_age_seconds=1)

        assert count == 1

        # Verify session is gone
        retrieved = await store.get_session(session.session_id)
        assert retrieved is None

    @pytest.mark.asyncio
    async def test_cleanup_keeps_active_sessions(self) -> None:
        """Test that cleanup doesn't remove active sessions."""
        store = MCPSessionStore()

        # Create sessions
        session1 = await store.create_session("key-1", "ghp_1")
        session2 = await store.create_session("key-2", "ghp_2")

        # Cleanup (should remove nothing)
        count = await store.cleanup_expired(max_age_seconds=3600)

        assert count == 0

        # Verify sessions still exist
        assert await store.get_session(session1.session_id) is not None
        assert await store.get_session(session2.session_id) is not None


# =====================================================================
# Test MCPMessageHandler
# =====================================================================


class TestMCPMessageHandler:
    """Test message handling."""

    @pytest.mark.asyncio
    async def test_handle_initialize(self) -> None:
        """Test handling initialize request."""
        mock_server = MagicMock()
        mock_server.__version__ = "0.1.0"
        handler = MCPMessageHandler(mock_server)

        message = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-03-26",
                "clientInfo": {"name": "test-client", "version": "1.0"},
                "capabilities": {"tools": True},
            },
        }

        response = await handler.handle_message(None, message)

        assert response is not None
        assert response["jsonrpc"] == "2.0"
        assert response["id"] == 1
        assert "result" in response
        assert response["result"]["protocolVersion"] == "2025-03-26"
        assert response["result"]["serverInfo"]["name"] == "github-pr-review"

    @pytest.mark.asyncio
    async def test_handle_tools_list(self) -> None:
        """Test handling tools/list request."""
        mock_server = MagicMock()
        mock_tool = MagicMock()
        mock_tool.model_dump.return_value = {
            "name": "test_tool",
            "description": "Test tool",
        }
        mock_server.handle_list_tools = AsyncMock(return_value=[mock_tool])

        handler = MCPMessageHandler(mock_server)

        session = MCPSession(
            session_id="test-123",
            mcp_key="key-abc",
            github_token="ghp_test",  # noqa: S106
            initialized=True,
        )

        message = {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}

        response = await handler.handle_message(session, message)

        assert response is not None
        assert response["jsonrpc"] == "2.0"
        assert response["id"] == 2
        assert "result" in response
        assert "tools" in response["result"]
        assert len(response["result"]["tools"]) == 1

    @pytest.mark.asyncio
    async def test_handle_tools_list_not_initialized(self) -> None:
        """Test tools/list fails when session not initialized."""
        mock_server = MagicMock()
        handler = MCPMessageHandler(mock_server)

        session = MCPSession(
            session_id="test-123",
            mcp_key="key-abc",
            github_token="ghp_test",  # noqa: S106
            initialized=False,  # Not initialized
        )

        message = {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}

        response = await handler.handle_message(session, message)

        assert response is not None
        assert "error" in response
        assert response["error"]["code"] == JSONRPC_INTERNAL_ERROR

    @pytest.mark.asyncio
    async def test_handle_tools_call(self) -> None:
        """Test handling tools/call request."""
        mock_server = MagicMock()
        mock_content = MagicMock()
        mock_content.text = "Test result"
        mock_server.handle_call_tool = AsyncMock(return_value=[mock_content])

        handler = MCPMessageHandler(mock_server)

        session = MCPSession(
            session_id="test-123",
            mcp_key="key-abc",
            github_token="ghp_test",  # noqa: S106
            initialized=True,
        )

        message = {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {
                "name": "test_tool",
                "arguments": {"arg1": "value1"},
            },
        }

        response = await handler.handle_message(session, message)

        assert response is not None
        assert response["jsonrpc"] == "2.0"
        assert response["id"] == 3
        assert "result" in response
        assert "content" in response["result"]
        assert response["result"]["content"][0]["text"] == "Test result"

        # Verify github_token was added to arguments
        mock_server.handle_call_tool.assert_called_once()
        call_args = mock_server.handle_call_tool.call_args
        assert call_args[0][1]["github_token"] == "ghp_test"  # noqa: S105

    @pytest.mark.asyncio
    async def test_handle_unknown_method(self) -> None:
        """Test handling unknown method."""
        mock_server = MagicMock()
        handler = MCPMessageHandler(mock_server)

        session = MCPSession(
            session_id="test-123",
            mcp_key="key-abc",
            github_token="ghp_test",  # noqa: S106
            initialized=True,
        )

        message = {
            "jsonrpc": "2.0",
            "id": 4,
            "method": "unknown/method",
            "params": {},
        }

        response = await handler.handle_message(session, message)

        assert response is not None
        assert "error" in response
        assert response["error"]["code"] == JSONRPC_METHOD_NOT_FOUND

    @pytest.mark.asyncio
    async def test_handle_notification(self) -> None:
        """Test handling notification (no response expected)."""
        mock_server = MagicMock()
        handler = MCPMessageHandler(mock_server)

        session = MCPSession(
            session_id="test-123",
            mcp_key="key-abc",
            github_token="ghp_test",  # noqa: S106
            initialized=True,
        )

        message = {
            "jsonrpc": "2.0",
            "method": "notifications/initialized",
            "params": {},
        }

        response = await handler.handle_message(session, message)

        # Notifications return None
        assert response is None

    @pytest.mark.asyncio
    async def test_handle_invalid_message(self) -> None:
        """Test handling invalid message structure."""
        mock_server = MagicMock()
        handler = MCPMessageHandler(mock_server)

        session = MCPSession(
            session_id="test-123",
            mcp_key="key-abc",
            github_token="ghp_test",  # noqa: S106
            initialized=True,
        )

        # Message without method
        message = {"jsonrpc": "2.0", "id": 5}

        response = await handler.handle_message(session, message)

        assert response is not None
        assert "error" in response
        assert response["error"]["code"] == JSONRPC_INVALID_REQUEST


# =====================================================================
# Test JSON-RPC Helper Functions
# =====================================================================


class TestJSONRPCHelpers:
    """Test protocol helper functions."""

    def test_parse_jsonrpc_message(self) -> None:
        """Test parsing JSON-RPC message."""
        message = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "test/method",
            "params": {"arg1": "value1"},
        }

        method, params = parse_jsonrpc_message(message)

        assert method == "test/method"
        assert params == {"arg1": "value1"}

    def test_parse_jsonrpc_message_no_params(self) -> None:
        """Test parsing message without params."""
        message = {"jsonrpc": "2.0", "id": 1, "method": "test/method"}

        method, params = parse_jsonrpc_message(message)

        assert method == "test/method"
        assert params == {}

    def test_create_jsonrpc_response(self) -> None:
        """Test creating success response."""
        response = create_jsonrpc_response(1, {"data": "test"})

        assert response["jsonrpc"] == "2.0"
        assert response["id"] == 1
        assert response["result"] == {"data": "test"}

    def test_create_jsonrpc_error(self) -> None:
        """Test creating error response."""
        error = create_jsonrpc_error(1, -32600, "Invalid request")

        assert error["jsonrpc"] == "2.0"
        assert error["id"] == 1
        assert error["error"]["code"] == -32600
        assert error["error"]["message"] == "Invalid request"

    def test_create_jsonrpc_error_with_data(self) -> None:
        """Test creating error with additional data."""
        error = create_jsonrpc_error(1, -32600, "Invalid request", {"detail": "test"})

        assert error["error"]["data"] == {"detail": "test"}

    def test_is_request(self) -> None:
        """Test identifying request messages."""
        request = {"jsonrpc": "2.0", "id": 1, "method": "test"}
        notification = {"jsonrpc": "2.0", "method": "test"}
        response = {"jsonrpc": "2.0", "id": 1, "result": {}}

        assert is_request(request) is True
        assert is_request(notification) is False
        assert is_request(response) is False

    def test_is_notification(self) -> None:
        """Test identifying notification messages."""
        request = {"jsonrpc": "2.0", "id": 1, "method": "test"}
        notification = {"jsonrpc": "2.0", "method": "test"}
        response = {"jsonrpc": "2.0", "id": 1, "result": {}}

        assert is_notification(request) is False
        assert is_notification(notification) is True
        assert is_notification(response) is False

    def test_is_response(self) -> None:
        """Test identifying response messages."""
        request = {"jsonrpc": "2.0", "id": 1, "method": "test"}
        notification = {"jsonrpc": "2.0", "method": "test"}
        success_response = {"jsonrpc": "2.0", "id": 1, "result": {}}
        error_response = {"jsonrpc": "2.0", "id": 1, "error": {}}

        assert is_response(request) is False
        assert is_response(notification) is False
        assert is_response(success_response) is True
        assert is_response(error_response) is True
