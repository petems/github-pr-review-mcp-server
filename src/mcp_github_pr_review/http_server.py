"""FastAPI HTTP server with SSE transport for MCP protocol.

This module implements an HTTP server that exposes the MCP GitHub PR Review
server over Server-Sent Events (SSE). It provides:
    - REST API endpoints for MCP tools
    - SSE endpoint for MCP protocol streaming
    - Authentication and rate limiting
    - Health checks and monitoring

Architecture:
    - FastAPI for HTTP routing and OpenAPI docs
    - sse-starlette for SSE streaming
    - MCP protocol over SSE events
    - Per-user GitHub token mapping

Security:
    - Bearer token authentication (MCP API keys)
    - Per-user rate limiting
    - CORS configuration
    - Admin API for token management
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sse_starlette import EventSourceResponse

from .auth import authenticate_and_rate_limit, verify_admin_token
from .config import get_settings
from .rate_limiter import get_rate_limiter
from .server import PRReviewServer
from .token_store import generate_mcp_key, get_token_store

# OAuth routes (conditionally included if enabled)
try:
    from . import oauth_routes
except ImportError:
    oauth_routes = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """FastAPI lifespan context manager.

    Handles server startup and shutdown, including:
    - Starting rate limiter background tasks
    - Cleanup on shutdown
    """
    logger.info("Starting MCP HTTP server")

    # Start rate limiter background task
    limiter = get_rate_limiter()
    await limiter.start()

    yield

    # Cleanup
    logger.info("Shutting down MCP HTTP server")
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
            "mcp_sse": "/sse",
            "admin": "/admin/*",
        },
        "stats": {
            "active_tokens": await token_store.count(),
            "rate_limit_buckets": await limiter.get_bucket_count(),
        },
    }


# =====================================================================
# MCP Tool Endpoints
# =====================================================================


class FetchCommentsRequest(BaseModel):
    """Request model for fetching PR comments."""

    pr_url: str | None = Field(default=None, description="GitHub PR URL")
    output: str = Field(
        default="markdown", description="Output format (markdown/json/both)"
    )
    per_page: int | None = Field(default=None, ge=1, le=100)
    max_pages: int | None = Field(default=None, ge=1, le=200)
    max_comments: int | None = Field(default=None, ge=100, le=100000)
    max_retries: int | None = Field(default=None, ge=0, le=10)
    owner: str | None = None
    repo: str | None = None
    branch: str | None = None
    select_strategy: str = "branch"


class FetchCommentsResponse(BaseModel):
    """Response model for fetching PR comments."""

    success: bool
    data: Any
    error: str | None = None


@app.post("/api/fetch-comments", tags=["mcp"], response_model=FetchCommentsResponse)
async def fetch_pr_comments(
    request: FetchCommentsRequest,
    auth: tuple[str, str] = Depends(authenticate_and_rate_limit),
) -> FetchCommentsResponse:
    """Fetch PR review comments (MCP tool endpoint).

    Args:
        request: Request parameters
        auth: Authentication tuple (mcp_key, github_token)

    Returns:
        PR comments in requested format
    """
    mcp_key, github_token = auth

    # Create MCP server instance with user's GitHub token
    # Store original env var and temporarily override
    original_token = os.environ.get("GITHUB_TOKEN")
    try:
        os.environ["GITHUB_TOKEN"] = github_token

        server = PRReviewServer()

        # Call the fetch_pr_review_comments method
        comments = await server.fetch_pr_review_comments(
            pr_url=request.pr_url,
            per_page=request.per_page,
            max_pages=request.max_pages,
            max_comments=request.max_comments,
            max_retries=request.max_retries,
            select_strategy=request.select_strategy,
            owner=request.owner,
            repo=request.repo,
            branch=request.branch,
        )

        # Format response based on output parameter
        if request.output == "json":
            return FetchCommentsResponse(success=True, data=comments)
        elif request.output == "markdown":
            from .server import generate_markdown

            markdown = generate_markdown(comments)
            return FetchCommentsResponse(success=True, data=markdown)
        else:  # both
            from .server import generate_markdown

            markdown = generate_markdown(comments)
            return FetchCommentsResponse(
                success=True,
                data={"json": comments, "markdown": markdown},
            )

    except Exception as e:
        logger.exception("Error fetching PR comments")
        return FetchCommentsResponse(
            success=False,
            data=None,
            error=str(e),
        )
    finally:
        # Restore original token
        if original_token:
            os.environ["GITHUB_TOKEN"] = original_token
        elif "GITHUB_TOKEN" in os.environ:
            del os.environ["GITHUB_TOKEN"]


# =====================================================================
# SSE Endpoint for MCP Protocol
# =====================================================================


@app.get("/sse", tags=["mcp"])
async def mcp_sse_endpoint(
    request: Request,
    auth: tuple[str, str] = Depends(authenticate_and_rate_limit),
) -> EventSourceResponse:
    """SSE endpoint for MCP protocol streaming.

    This endpoint provides Server-Sent Events for the MCP protocol,
    allowing clients to stream MCP messages over HTTP.

    Args:
        request: FastAPI request
        auth: Authentication tuple (mcp_key, github_token)

    Returns:
        SSE event stream
    """
    mcp_key, github_token = auth

    async def event_generator() -> AsyncIterator[dict[str, str]]:
        """Generate SSE events for MCP protocol."""
        try:
            # Send connection established event
            yield {
                "event": "connected",
                "data": json.dumps(
                    {
                        "status": "connected",
                        "mcp_version": "1.0",
                    }
                ),
            }

            # Keep connection alive with periodic pings
            while True:
                if await request.is_disconnected():
                    break

                yield {
                    "event": "ping",
                    "data": json.dumps({"timestamp": asyncio.get_event_loop().time()}),
                }

                await asyncio.sleep(30)  # Ping every 30 seconds

        except asyncio.CancelledError:
            logger.info(
                "SSE connection cancelled", extra={"key_prefix": mcp_key[:8] + "..."}
            )
        except Exception:
            logger.exception("Error in SSE event generator")

    return EventSourceResponse(event_generator())


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
