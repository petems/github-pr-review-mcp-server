"""FastAPI HTTP server with MCP Streaming HTTP transport.

This module implements an HTTP server that exposes the MCP GitHub PR Review
server over the MCP Streaming HTTP protocol (spec: 2025-03-26). It provides:
    - MCP JSON-RPC endpoints (POST/DELETE /mcp)
    - Session management with automatic cleanup
    - Authentication and rate limiting
    - Health checks and monitoring
    - Admin API for token management

Architecture:
    - FastAPI for HTTP routing and OpenAPI docs
    - Pure HTTP streaming with JSON-RPC
    - MCP protocol over HTTP
    - Per-user GitHub token mapping via sessions

Security:
    - Bearer token authentication (MCP API keys)
    - Per-user rate limiting
    - CORS configuration
    - Session-based authentication after initialize
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from .auth import authenticate_and_rate_limit, verify_admin_token
from .config import get_settings
from .mcp_transport import (
    MCPMessageHandler,
    MCPSessionStore,
    create_jsonrpc_error,
    is_request,
)
from .rate_limiter import get_rate_limiter
from .server import PRReviewServer
from .token_store import generate_mcp_key, get_token_store

# OAuth routes (conditionally included if enabled)
try:
    from . import oauth_routes
except ImportError:
    oauth_routes = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

# Initialize MCP transport components
pr_review_server = PRReviewServer()
mcp_session_store = MCPSessionStore()
mcp_handler = MCPMessageHandler(pr_review_server)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """FastAPI lifespan context manager.

    Handles server startup and shutdown, including:
    - Starting rate limiter background tasks
    - Starting session cleanup task
    - Cleanup on shutdown
    """
    logger.info("Starting MCP HTTP server")

    # Start rate limiter background task
    limiter = get_rate_limiter()
    await limiter.start()

    # Start session cleanup task
    async def cleanup_sessions() -> None:
        while True:
            await asyncio.sleep(300)  # Every 5 minutes
            count = await mcp_session_store.cleanup_expired(max_age_seconds=3600)
            if count > 0:
                logger.info(f"Cleaned up {count} expired MCP sessions")

    cleanup_task = asyncio.create_task(cleanup_sessions())

    yield

    # Cleanup
    logger.info("Shutting down MCP HTTP server")
    cleanup_task.cancel()
    try:
        await cleanup_task
    except asyncio.CancelledError:
        pass
    await limiter.stop()


# Create FastAPI app
app = FastAPI(
    title="GitHub PR Review MCP Server",
    description="MCP server for fetching and formatting GitHub PR review comments",
    version="0.1.0",
    lifespan=lifespan,
)


# Configure CORS
settings = get_settings()
if settings.cors_enabled:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.get_cors_origins(),
        allow_credentials=settings.cors_allow_credentials,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
        expose_headers=[
            "X-RateLimit-Limit",
            "X-RateLimit-Remaining",
            "X-RateLimit-Reset",
            "Retry-After",
        ],
    )


# Configure OAuth routes (if enabled)
if settings.github_oauth_enabled and oauth_routes:
    logger.info("OAuth is enabled - including OAuth authentication routes")
    app.include_router(oauth_routes.router)
else:
    logger.info("OAuth is disabled - OAuth routes not included")


# =====================================================================
# OAuth Discovery Endpoint
# =====================================================================


@app.get("/.well-known/oauth-authorization-server", tags=["authentication"])
async def oauth_discovery_metadata(request: Request) -> dict[str, Any]:
    """OAuth 2.0 authorization server metadata endpoint.

    Required for MCP clients to automatically discover authentication endpoints.
    See: RFC 8414 (OAuth 2.0 Authorization Server Metadata)

    Returns:
        OAuth server metadata including endpoints and supported features
    """
    # Build base URL from request
    base_url = str(request.base_url).rstrip("/")

    return {
        "issuer": base_url,
        "authorization_endpoint": f"{base_url}/auth/login",
        "token_endpoint": f"{base_url}/auth/token",
        "scopes_supported": ["repo", "read:user"],
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code"],
        "token_endpoint_auth_methods_supported": ["none"],
    }


# =====================================================================
# Health and Status Endpoints
# =====================================================================


@app.get("/health", tags=["monitoring"])
async def health_check() -> dict[str, str]:
    """Health check endpoint.

    Returns:
        Status information
    """
    return {
        "status": "healthy",
        "service": "github-pr-review-mcp",
        "version": "0.1.0",
    }


@app.get("/", tags=["info"])
async def root() -> dict[str, Any]:
    """Root endpoint with server information.

    Returns:
        Server metadata
    """
    token_store = get_token_store()
    limiter = get_rate_limiter()

    return {
        "service": "GitHub PR Review MCP Server",
        "version": "0.1.0",
        "mode": "http",
        "endpoints": {
            "health": "/health",
            "docs": "/docs",
            "mcp": "/mcp (POST/DELETE)",
            "admin": "/admin/*",
        },
        "stats": {
            "active_tokens": await token_store.count(),
            "rate_limit_buckets": await limiter.get_bucket_count(),
        },
    }


# =====================================================================
# MCP Protocol Endpoints (JSON-RPC over HTTP)
# =====================================================================


@app.post("/mcp", tags=["mcp"])
async def mcp_post_endpoint(
    request: Request,
    auth: tuple[str, str] = Depends(authenticate_and_rate_limit),
) -> Any:
    """Handle client→server JSON-RPC messages.

    Accepts:
    - Single JSON-RPC request/notification/response
    - Batch of requests/notifications/responses

    Returns:
    - 202 Accepted (for notifications/responses only)
    - JSON response (for requests)
    - Streaming response (for long-running operations if needed)

    Args:
        request: FastAPI request
        auth: Authentication tuple (mcp_key, github_token)

    Returns:
        JSON response or 202 Accepted
    """
    mcp_key, github_token = auth

    # Parse session ID from header
    session_id = request.headers.get("Mcp-Session-Id")

    # Get or create session
    if session_id:
        session = await mcp_session_store.get_session(session_id)
        if not session:
            return JSONResponse({"error": "Session not found"}, status_code=404)
        # Update activity
        await mcp_session_store.update_activity(session_id)
    else:
        # No session ID - only valid for initialize
        session = None

    # Parse JSON-RPC message(s)
    try:
        body = await request.json()
    except json.JSONDecodeError:
        return JSONResponse(
            create_jsonrpc_error(None, -32700, "Parse error"), status_code=400
        )

    messages = body if isinstance(body, list) else [body]

    # Check if all are notifications/responses (no requests)
    has_requests = any(is_request(msg) for msg in messages)

    if not has_requests:
        # Process notifications/responses (no response needed)
        for msg in messages:
            await mcp_handler.handle_message(session, msg)
        return Response(status_code=202)

    # Has requests - need to respond
    # For quick operations: return JSON
    # For initialize or potential streaming: use SSE

    is_initialize = any(
        msg.get("method") == "initialize" for msg in messages if is_request(msg)
    )

    if is_initialize:
        # Initialize always returns JSON + creates session
        result = await mcp_handler.handle_message(None, messages[0])

        # Create session
        new_session = await mcp_session_store.create_session(mcp_key, github_token)

        # Mark session as initialized
        new_session.initialized = True
        new_session.client_info = messages[0].get("params", {}).get("clientInfo", {})
        new_session.capabilities = messages[0].get("params", {}).get("capabilities", {})

        headers = {"Mcp-Session-Id": new_session.session_id}
        return JSONResponse(result, headers=headers)

    # Non-initialize requests - use standard JSON responses
    responses = []
    for msg in messages:
        if is_request(msg):
            result = await mcp_handler.handle_message(session, msg)
            responses.append(result)

    # Return single response or batch
    result_data = responses[0] if len(responses) == 1 else responses
    return JSONResponse(result_data)


@app.delete("/mcp", tags=["mcp"])
async def mcp_delete_endpoint(
    request: Request,
    auth: tuple[str, str] = Depends(authenticate_and_rate_limit),
) -> Any:
    """Terminate MCP session.

    Client calls this when leaving the application.

    Args:
        request: FastAPI request
        auth: Authentication tuple (mcp_key, github_token)

    Returns:
        204 No Content or error response
    """
    # Get session ID
    session_id = request.headers.get("Mcp-Session-Id")
    if not session_id:
        return JSONResponse({"error": "Mcp-Session-Id required"}, status_code=400)

    # Delete session
    deleted = await mcp_session_store.delete_session(session_id)
    if not deleted:
        return JSONResponse({"error": "Session not found"}, status_code=404)

    return Response(status_code=204)


# =====================================================================
# Admin API (Token Management)
# =====================================================================


class CreateTokenRequest(BaseModel):
    """Request model for creating a token mapping."""

    github_token: str = Field(..., description="GitHub Personal Access Token")
    user_id: str | None = Field(default=None, description="Optional user identifier")
    description: str | None = Field(default=None, description="Optional description")


class CreateTokenResponse(BaseModel):
    """Response model for creating a token mapping."""

    mcp_key: str = Field(..., description="Generated MCP API key")
    user_id: str | None = None
    description: str | None = None
    created_at: str


class TokenInfo(BaseModel):
    """Information about a token mapping (without exposing secrets)."""

    mcp_key: str
    user_id: str | None
    description: str | None
    created_at: str
    last_used_at: str
    github_token_prefix: str  # First 8 chars + ...


@app.post("/admin/tokens", tags=["admin"], response_model=CreateTokenResponse)
async def create_token(
    request: CreateTokenRequest,
    _auth: None = Depends(verify_admin_token),
) -> CreateTokenResponse:
    """Create a new MCP API key and GitHub token mapping.

    Requires admin authentication.

    Args:
        request: Token creation request
        _auth: Admin authentication (dependency)

    Returns:
        Created token information
    """
    token_store = get_token_store()

    # Generate new MCP API key
    mcp_key = generate_mcp_key()

    # Store mapping
    await token_store.store_token(
        mcp_key=mcp_key,
        github_token=request.github_token,
        user_id=request.user_id,
        description=request.description,
    )

    # Get the mapping to return creation time
    mapping = await token_store.get_mapping(mcp_key)

    return CreateTokenResponse(
        mcp_key=mcp_key,
        user_id=request.user_id,
        description=request.description,
        created_at=mapping.created_at.isoformat() if mapping else "",
    )


@app.get("/admin/tokens", tags=["admin"], response_model=list[TokenInfo])
async def list_tokens(
    _auth: None = Depends(verify_admin_token),
) -> list[TokenInfo]:
    """List all token mappings.

    Requires admin authentication.

    Args:
        _auth: Admin authentication (dependency)

    Returns:
        List of token information (without exposing full secrets)
    """
    token_store = get_token_store()
    mappings = await token_store.list_tokens()

    return [
        TokenInfo(
            mcp_key=m.mcp_key,
            user_id=m.user_id,
            description=m.description,
            created_at=m.created_at.isoformat(),
            last_used_at=m.last_used_at.isoformat(),
            github_token_prefix=m.github_token[:8] + "..." if m.github_token else "N/A",
        )
        for m in mappings
    ]


@app.delete("/admin/tokens/{mcp_key}", tags=["admin"])
async def delete_token(
    mcp_key: str,
    _auth: None = Depends(verify_admin_token),
) -> dict[str, str]:
    """Delete a token mapping.

    Requires admin authentication.

    Args:
        mcp_key: MCP API key to delete
        _auth: Admin authentication (dependency)

    Returns:
        Deletion status
    """
    token_store = get_token_store()
    deleted = await token_store.delete_token(mcp_key)

    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Token not found",
        )

    return {"status": "deleted", "mcp_key": mcp_key}


# =====================================================================
# Main Entry Point
# =====================================================================


def main() -> int:
    """Main entry point for HTTP server mode."""
    import uvicorn

    settings = get_settings()

    if settings.mcp_mode != "http":
        print("Error: MCP_MODE must be 'http' to run HTTP server", file=sys.stderr)
        return 1

    logger.info(
        "Starting HTTP server",
        extra={
            "host": settings.mcp_host,
            "port": settings.mcp_port,
        },
    )

    uvicorn.run(
        app,
        host=settings.mcp_host,
        port=settings.mcp_port,
        log_level="info",
    )

    return 0


if __name__ == "__main__":
    sys.exit(main())
