"""OAuth authentication routes for FastAPI server.

This module provides HTTP endpoints for the GitHub OAuth flow:
- /.well-known/oauth-authorization-server: OAuth discovery metadata
- /auth/login: Initiates OAuth flow
- /auth/callback: Handles OAuth callback (HTML response)
- /auth/token: Token endpoint for programmatic OAuth
- /auth/status: Check authentication status
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel

from .config import get_settings
from .oauth import (
    ERROR_PAGE_TEMPLATE,
    SUCCESS_PAGE_TEMPLATE,
    GitHubOAuthClient,
    get_oauth_state_store,
)
from .token_store import generate_mcp_key, get_token_store

logger = logging.getLogger(__name__)

# Create router for OAuth endpoints
router = APIRouter(prefix="/auth", tags=["authentication"])


# Pydantic models for token endpoint
class TokenRequest(BaseModel):
    """OAuth token request."""

    grant_type: str
    code: str | None = None
    client_id: str | None = None
    client_secret: str | None = None
    redirect_uri: str | None = None


class TokenResponse(BaseModel):
    """OAuth token response."""

    access_token: str
    token_type: str
    expires_in: int | None = None
    scope: str | None = None


@router.get("/login")
async def oauth_login(
    request: Request,
    redirect_uri: str | None = Query(
        default=None, description="Redirect after success"
    ),
) -> RedirectResponse:
    """Initiate GitHub OAuth flow.

    This endpoint:
    1. Generates a CSRF state token
    2. Stores state in temporary storage
    3. Redirects user to GitHub OAuth consent page

    Args:
        request: FastAPI request
        redirect_uri: Optional redirect URL after successful auth

    Returns:
        RedirectResponse to GitHub OAuth
    """
    settings = get_settings()

    # Check if OAuth is configured
    if not settings.github_oauth_enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="OAuth authentication is not enabled. Contact administrator.",
        )

    # Create OAuth client
    oauth_client = GitHubOAuthClient(settings)

    # Generate and store state for CSRF protection
    state_store = get_oauth_state_store()
    state = await state_store.create_state(redirect_uri=redirect_uri)

    # Generate authorization URL
    auth_url = oauth_client.get_authorization_url(state)

    logger.info(
        "Initiating OAuth flow",
        extra={
            "state_prefix": state[:8] + "...",
            "redirect_uri": redirect_uri,
        },
    )

    return RedirectResponse(auth_url)


@router.get("/callback")
async def oauth_callback(
    request: Request,
    code: str = Query(..., description="OAuth authorization code"),
    state: str = Query(..., description="CSRF state token"),
    error: str | None = Query(default=None, description="OAuth error"),
    error_description: str | None = Query(
        default=None, description="Error description"
    ),
) -> HTMLResponse:
    """Handle GitHub OAuth callback.

    This endpoint:
    1. Verifies CSRF state token
    2. Exchanges authorization code for access token
    3. Creates MCP API key and stores mapping
    4. Displays success page with MCP key

    Args:
        request: FastAPI request
        code: Authorization code from GitHub
        state: CSRF state token
        error: OAuth error (if any)
        error_description: Error description

    Returns:
        HTMLResponse with success or error page
    """
    settings = get_settings()

    # Handle OAuth errors
    if error:
        logger.warning(
            "OAuth error from GitHub",
            extra={"error": error, "description": error_description},
        )
        return HTMLResponse(
            ERROR_PAGE_TEMPLATE.format(
                error_message=error_description or error or "Unknown error",
            ),
            status_code=400,
        )

    # Verify state (CSRF protection)
    state_store = get_oauth_state_store()
    oauth_state = await state_store.verify_state(state)

    if oauth_state is None:
        logger.warning("Invalid or expired OAuth state")
        error_msg = "Invalid or expired authentication state. Please try again."
        return HTMLResponse(
            ERROR_PAGE_TEMPLATE.format(error_message=error_msg),
            status_code=400,
        )

    try:
        # Exchange code for token
        oauth_client = GitHubOAuthClient(settings)
        github_token, user_info = await oauth_client.exchange_code(code)

        # Extract user information
        username = user_info.get("login", "unknown")
        user_id = str(user_info.get("id", username))

        # Generate MCP API key
        mcp_key = generate_mcp_key()

        # Store token mapping
        token_store = get_token_store()
        await token_store.store_token(
            mcp_key=mcp_key,
            github_token=github_token,
            user_id=user_id,
            description=f"Self-service auth for {username}",
        )

        logger.info(
            "OAuth flow completed successfully",
            extra={
                "username": username,
                "user_id": user_id,
                "mcp_key_prefix": mcp_key[:8] + "...",
            },
        )

        # Render success page with MCP key
        return HTMLResponse(
            SUCCESS_PAGE_TEMPLATE.format(
                username=username,
                mcp_key=mcp_key,
                created_at=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
            )
        )

    except HTTPException as e:
        logger.error("OAuth flow failed", extra={"detail": e.detail})
        return HTMLResponse(
            ERROR_PAGE_TEMPLATE.format(error_message=e.detail),
            status_code=e.status_code,
        )
    except Exception:
        logger.exception("Unexpected error in OAuth callback")
        error_msg = "An unexpected error occurred. Please try again or contact support."
        return HTMLResponse(
            ERROR_PAGE_TEMPLATE.format(error_message=error_msg),
            status_code=500,
        )


@router.post("/token")
async def token_endpoint(
    request: Request,
    token_request: TokenRequest,
) -> JSONResponse:
    """OAuth 2.0 token endpoint for programmatic access.

    This endpoint exchanges an authorization code for an access token (MCP API key).
    Used by MCP clients for automated OAuth flows.

    Args:
        request: FastAPI request
        token_request: Token request parameters

    Returns:
        JSONResponse with access token
    """
    settings = get_settings()

    if not settings.github_oauth_enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="OAuth authentication is not enabled",
        )

    # Only support authorization_code grant type
    if token_request.grant_type != "authorization_code":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unsupported grant_type. Only 'authorization_code' is supported.",
        )

    if not token_request.code:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing 'code' parameter",
        )

    try:
        # Exchange code for GitHub token
        oauth_client = GitHubOAuthClient(settings)
        github_token, user_info = await oauth_client.exchange_code(token_request.code)

        # Extract user information
        username = user_info.get("login", "unknown")
        user_id = str(user_info.get("id", username))

        # Generate MCP API key
        mcp_key = generate_mcp_key()

        # Store token mapping
        token_store = get_token_store()
        await token_store.store_token(
            mcp_key=mcp_key,
            github_token=github_token,
            user_id=user_id,
            description=f"OAuth token for {username}",
        )

        logger.info(
            "Token endpoint: issued access token",
            extra={
                "username": username,
                "user_id": user_id,
                "mcp_key_prefix": mcp_key[:8] + "...",
            },
        )

        # Return OAuth token response
        response_data = TokenResponse(
            access_token=mcp_key,
            token_type="bearer",  # noqa: S106
            expires_in=None,  # No expiration (or set a TTL)
            scope="repo read:user",
        )

        return JSONResponse(
            content=response_data.model_dump(),
            status_code=200,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error in token endpoint")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to issue access token",
        ) from e


@router.get("/status")
async def auth_status() -> dict[str, Any]:
    """Check OAuth authentication status.

    Returns:
        Status information about OAuth configuration
    """
    settings = get_settings()

    return {
        "oauth_enabled": settings.github_oauth_enabled,
        "oauth_configured": bool(
            settings.github_oauth_client_id and settings.github_oauth_client_secret
        ),
        "login_url": "/auth/login" if settings.github_oauth_enabled else None,
    }
