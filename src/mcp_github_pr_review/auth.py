"""Authentication middleware and utilities for MCP HTTP server.

This module provides API key authentication for the HTTP/SSE transport.
It validates MCP API keys, retrieves associated GitHub tokens, and enforces
rate limits on a per-user basis.

Security Model:
    - API keys are passed in the Authorization header (Bearer scheme)
    - Each API key maps to a GitHub token (stored in token_store)
    - Rate limiting is enforced per API key
    - Admin operations require admin token
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from fastapi import Header, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .config import get_settings
from .rate_limiter import get_rate_limiter
from .token_store import get_token_store

if TYPE_CHECKING:
    from .rate_limiter import RateLimitInfo

logger = logging.getLogger(__name__)

# HTTP Bearer authentication scheme
bearer_scheme = HTTPBearer(auto_error=False)


class AuthenticationError(Exception):
    """Raised when authentication fails."""

    def __init__(self, message: str, status_code: int = status.HTTP_401_UNAUTHORIZED):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


class RateLimitExceeded(Exception):
    """Raised when rate limit is exceeded."""

    def __init__(self, limit_info: RateLimitInfo):
        self.limit_info = limit_info
        message = (
            f"Rate limit exceeded. "
            f"Limit: {limit_info.limit} requests per minute. "
            f"Try again in {limit_info.retry_after:.1f} seconds."
        )
        super().__init__(message)


async def verify_mcp_key(authorization: str | None = Header(None)) -> str:
    """Verify MCP API key from Authorization header.

    Args:
        authorization: Authorization header value (Bearer token)

    Returns:
        The validated MCP API key

    Raises:
        HTTPException: If authentication fails (401 Unauthorized)

    Example:
        >>> # In a FastAPI endpoint:
        >>> @app.get("/protected")
        >>> async def protected(mcp_key: str = Depends(verify_mcp_key)):
        >>>     # mcp_key is validated and ready to use
        >>>     pass
    """
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization header",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Parse Bearer token
    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Authorization header format. Expected: Bearer <token>",
            headers={"WWW-Authenticate": "Bearer"},
        )

    mcp_key = parts[1]

    # Validate key format (basic sanity check)
    if not mcp_key or len(mcp_key) < 10:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key format",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Check if key exists in token store
    token_store = get_token_store()
    if not await token_store.exists(mcp_key):
        logger.warning(
            "Authentication failed: unknown API key",
            extra={"key_prefix": mcp_key[:8] + "..."},
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
            headers={"WWW-Authenticate": "Bearer"},
        )

    logger.debug(
        "Authentication successful",
        extra={"key_prefix": mcp_key[:8] + "..."},
    )

    return mcp_key


async def verify_admin_token(authorization: str | None = Header(None)) -> None:
    """Verify admin token from Authorization header.

    Admin token is configured via MCP_ADMIN_TOKEN environment variable.
    Used to protect admin endpoints like token management.

    Args:
        authorization: Authorization header value (Bearer token)

    Raises:
        HTTPException: If admin authentication fails (401/403)
    """
    settings = get_settings()

    if not settings.mcp_admin_token:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Admin API is not configured (MCP_ADMIN_TOKEN not set)",
        )

    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization header",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Parse Bearer token
    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Authorization header format. Expected: Bearer <token>",
            headers={"WWW-Authenticate": "Bearer"},
        )

    provided_token = parts[1]
    expected_token = settings.mcp_admin_token.get_secret_value()

    if provided_token != expected_token:
        logger.warning("Admin authentication failed: invalid token")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid admin token",
        )

    logger.info("Admin authentication successful")


async def get_github_token(mcp_key: str) -> str:
    """Get GitHub token for an authenticated MCP API key.

    Args:
        mcp_key: The validated MCP API key

    Returns:
        GitHub Personal Access Token

    Raises:
        HTTPException: If token mapping not found (500 Internal Server Error)
    """
    token_store = get_token_store()
    github_token = await token_store.get_github_token(mcp_key)

    if not github_token:
        logger.error(
            "GitHub token not found for authenticated key",
            extra={"key_prefix": mcp_key[:8] + "..."},
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="GitHub token configuration error",
        )

    return github_token


async def check_rate_limit(mcp_key: str) -> None:
    """Check rate limit for an MCP API key.

    Args:
        mcp_key: The MCP API key to check

    Raises:
        HTTPException: If rate limit exceeded (429 Too Many Requests)
    """
    settings = get_settings()

    if not settings.rate_limit_enabled:
        return

    limiter = get_rate_limiter()
    limit_info = await limiter.check_limit(
        key=mcp_key,
        limit=settings.rate_limit_requests_per_minute,
        window_seconds=60,
        burst=settings.rate_limit_burst,
    )

    if not limit_info.allowed:
        logger.warning(
            "Rate limit exceeded",
            extra={
                "key_prefix": mcp_key[:8] + "...",
                "limit": limit_info.limit,
                "retry_after": limit_info.retry_after,
            },
        )
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Rate limit exceeded. Try again in {limit_info.retry_after:.1f} seconds.",
            headers={
                "Retry-After": str(int(limit_info.retry_after)),
                "X-RateLimit-Limit": str(limit_info.limit),
                "X-RateLimit-Remaining": str(limit_info.remaining),
                "X-RateLimit-Reset": str(int(limit_info.reset_at)),
            },
        )


async def authenticate_and_rate_limit(request: Request) -> tuple[str, str]:
    """Combined authentication and rate limiting middleware.

    This is the main authentication function to use in FastAPI dependencies.
    It performs both API key validation and rate limit checking.

    Args:
        request: FastAPI Request object

    Returns:
        Tuple of (mcp_key, github_token)

    Raises:
        HTTPException: If authentication or rate limiting fails

    Example:
        >>> @app.get("/api/endpoint")
        >>> async def endpoint(auth: tuple[str, str] = Depends(authenticate_and_rate_limit)):
        >>>     mcp_key, github_token = auth
        >>>     # Use github_token for GitHub API calls
        >>>     pass
    """
    # Extract Authorization header
    auth_header = request.headers.get("authorization")

    # Verify MCP API key
    mcp_key = await verify_mcp_key(authorization=auth_header)

    # Check rate limit
    await check_rate_limit(mcp_key)

    # Get GitHub token
    github_token = await get_github_token(mcp_key)

    return mcp_key, github_token


def get_client_identifier(request: Request) -> str:
    """Get a client identifier for logging/debugging.

    Uses X-Forwarded-For if behind a proxy, otherwise uses client IP.

    Args:
        request: FastAPI Request object

    Returns:
        Client identifier (IP address)
    """
    # Check for proxy headers
    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        # Take the first IP in the chain
        return forwarded_for.split(",")[0].strip()

    # Fall back to direct client IP
    if request.client:
        return request.client.host

    return "unknown"
