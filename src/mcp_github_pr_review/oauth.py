"""GitHub OAuth authentication flow for self-service token creation.

This module implements the OAuth 2.0 authorization code flow, allowing users
to authenticate with GitHub and automatically receive their MCP API key without
requiring admin intervention.

Flow:
    1. User visits /auth/login
    2. Redirect to GitHub OAuth consent page
    3. User authorizes app with specific scopes
    4. GitHub redirects to /auth/callback with code
    5. Exchange code for GitHub access token
    6. Generate MCP API key and store mapping
    7. Display MCP key to user (one-time view)

Security:
    - State parameter for CSRF protection
    - Temporary state storage (expires in 10 minutes)
    - One-time token display (copy-once)
    - Scope validation (only request minimal permissions)
"""

from __future__ import annotations

import asyncio
import logging
import secrets
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import httpx
from fastapi import HTTPException, status

if TYPE_CHECKING:
    from .config import ServerSettings

logger = logging.getLogger(__name__)


@dataclass
class OAuthState:
    """Represents an OAuth state for CSRF protection.

    Attributes:
        state: Random state string
        created_at: Timestamp when state was created
        redirect_uri: Optional redirect after successful auth
    """

    state: str
    created_at: float
    redirect_uri: str | None = None


class OAuthStateStore:
    """Temporary storage for OAuth states (CSRF protection).

    States expire after 10 minutes to prevent replay attacks.
    Uses in-memory storage (could be upgraded to Redis).
    """

    def __init__(self, ttl_seconds: int = 600) -> None:
        """Initialize the OAuth state store.

        Args:
            ttl_seconds: Time-to-live for states (default: 10 minutes)
        """
        self._states: dict[str, OAuthState] = {}
        self._lock = asyncio.Lock()
        self._ttl = ttl_seconds
        logger.info("Initialized OAuth state store", extra={"ttl_seconds": ttl_seconds})

    async def create_state(self, redirect_uri: str | None = None) -> str:
        """Create a new OAuth state.

        Args:
            redirect_uri: Optional redirect after successful auth

        Returns:
            The generated state string
        """
        async with self._lock:
            # Generate secure random state (256 bits)
            state = secrets.token_urlsafe(32)

            # Store state with metadata
            self._states[state] = OAuthState(
                state=state,
                created_at=time.time(),
                redirect_uri=redirect_uri,
            )

            logger.debug(
                "Created OAuth state", extra={"state_prefix": state[:8] + "..."}
            )
            return state

    async def verify_state(self, state: str) -> OAuthState | None:
        """Verify and consume an OAuth state.

        Args:
            state: The state string to verify

        Returns:
            OAuthState if valid and not expired, None otherwise
        """
        async with self._lock:
            oauth_state = self._states.get(state)

            if oauth_state is None:
                logger.warning(
                    "OAuth state not found", extra={"state_prefix": state[:8] + "..."}
                )
                return None

            # Check expiration
            age = time.time() - oauth_state.created_at
            if age > self._ttl:
                logger.warning(
                    "OAuth state expired",
                    extra={"state_prefix": state[:8] + "...", "age_seconds": age},
                )
                del self._states[state]
                return None

            # Consume state (one-time use)
            del self._states[state]

            logger.debug(
                "OAuth state verified", extra={"state_prefix": state[:8] + "..."}
            )
            return oauth_state

    async def cleanup_expired(self) -> int:
        """Remove expired states from storage.

        Returns:
            Number of states removed
        """
        async with self._lock:
            current_time = time.time()
            expired = [
                state
                for state, oauth_state in self._states.items()
                if current_time - oauth_state.created_at > self._ttl
            ]

            for state in expired:
                del self._states[state]

            if expired:
                logger.debug(
                    "Cleaned up expired OAuth states", extra={"count": len(expired)}
                )

            return len(expired)


class GitHubOAuthClient:
    """Client for GitHub OAuth 2.0 flow.

    Handles OAuth redirect, token exchange, and scope validation.
    """

    # GitHub OAuth URLs
    AUTHORIZE_URL = "https://github.com/login/oauth/authorize"
    TOKEN_URL = "https://github.com/login/oauth/access_token"  # noqa: S105
    USER_URL = "https://api.github.com/user"

    # Required scopes for PR review functionality
    DEFAULT_SCOPES = ["repo", "read:user"]  # Can be more granular

    def __init__(self, settings: ServerSettings) -> None:
        """Initialize the GitHub OAuth client.

        Args:
            settings: Server settings with OAuth configuration
        """
        self.client_id = settings.github_oauth_client_id
        self.client_secret = settings.github_oauth_client_secret
        self.callback_url = settings.github_oauth_callback_url
        self.scopes = (
            settings.github_oauth_scopes.split(",")
            if settings.github_oauth_scopes
            else self.DEFAULT_SCOPES
        )

    def get_authorization_url(self, state: str, scopes: list[str] | None = None) -> str:
        """Generate GitHub OAuth authorization URL.

        Args:
            state: CSRF protection state
            scopes: Requested OAuth scopes (default: repo, read:user)

        Returns:
            Authorization URL to redirect user to
        """
        scope_list = scopes or self.scopes
        scope_str = " ".join(scope_list)

        params = {
            "client_id": self.client_id,
            "redirect_uri": self.callback_url,
            "scope": scope_str,
            "state": state,
        }

        # Build URL with query parameters
        query_string = "&".join(f"{k}={v}" for k, v in params.items())
        url = f"{self.AUTHORIZE_URL}?{query_string}"

        logger.info(
            "Generated OAuth authorization URL",
            extra={"scopes": scope_list, "state_prefix": state[:8] + "..."},
        )

        return url

    async def exchange_code(self, code: str) -> tuple[str, dict[str, Any]]:
        """Exchange authorization code for access token.

        Args:
            code: Authorization code from GitHub callback

        Returns:
            Tuple of (access_token, user_info)

        Raises:
            HTTPException: If token exchange fails
        """
        logger.info("Exchanging OAuth code for access token")

        if not self.client_secret:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="OAuth client secret not configured",
            )

        async with httpx.AsyncClient() as client:
            # Exchange code for token
            response = await client.post(
                self.TOKEN_URL,
                headers={"Accept": "application/json"},
                data={
                    "client_id": self.client_id,
                    "client_secret": self.client_secret.get_secret_value(),
                    "code": code,
                    "redirect_uri": self.callback_url,
                },
            )

            if response.status_code != 200:
                logger.error(
                    "Failed to exchange OAuth code",
                    extra={
                        "status_code": response.status_code,
                        "response": response.text,
                    },
                )
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail="Failed to exchange authorization code with GitHub",
                )

            data = response.json()

            if "error" in data:
                logger.error(
                    "GitHub OAuth error", extra={"error": data.get("error_description")}
                )
                error_desc = data.get("error_description", "Unknown error")
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"OAuth error: {error_desc}",
                )

            access_token = data.get("access_token")
            if not access_token:
                logger.error("No access token in GitHub response")
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail="GitHub did not return an access token",
                )

            # Fetch user information
            user_response = await client.get(
                self.USER_URL,
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Accept": "application/json",
                },
            )

            if user_response.status_code != 200:
                logger.error(
                    "Failed to fetch user info",
                    extra={"status_code": user_response.status_code},
                )
                user_info = {"login": "unknown"}
            else:
                user_info = user_response.json()

            logger.info(
                "Successfully exchanged OAuth code",
                extra={
                    "user_login": user_info.get("login"),
                    "scopes": data.get("scope"),
                },
            )

            return access_token, user_info


# Global state store instance
_state_store: OAuthStateStore | None = None


def get_oauth_state_store() -> OAuthStateStore:
    """Get or create the global OAuth state store.

    Returns:
        The global OAuthStateStore instance
    """
    global _state_store
    if _state_store is None:
        _state_store = OAuthStateStore()
    return _state_store


# HTML templates for OAuth flow
SUCCESS_PAGE_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Authentication Successful - MCP Server</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI',
                Roboto, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 20px;
        }}
        .container {{
            background: white;
            border-radius: 16px;
            box-shadow: 0 20px 60px rgba(0,0,0,0.3);
            max-width: 600px;
            width: 100%;
            padding: 40px;
            text-align: center;
        }}
        .success-icon {{
            width: 80px;
            height: 80px;
            background: #10b981;
            border-radius: 50%;
            margin: 0 auto 24px;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 48px;
        }}
        h1 {{ color: #1f2937; margin-bottom: 16px; font-size: 28px; }}
        .user-info {{
            background: #f3f4f6;
            padding: 16px;
            border-radius: 8px;
            margin: 24px 0;
            font-size: 14px;
            color: #6b7280;
        }}
        .token-container {{
            background: #fef3c7;
            border: 2px solid #fbbf24;
            border-radius: 8px;
            padding: 20px;
            margin: 24px 0;
        }}
        .token-label {{
            font-weight: 600;
            color: #92400e;
            margin-bottom: 8px;
            font-size: 14px;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }}
        .token-value {{
            background: white;
            padding: 12px;
            border-radius: 6px;
            font-family: 'Courier New', monospace;
            font-size: 14px;
            word-break: break-all;
            color: #1f2937;
            border: 1px solid #d1d5db;
        }}
        .copy-button {{
            background: #3b82f6;
            color: white;
            border: none;
            padding: 12px 24px;
            border-radius: 8px;
            font-size: 16px;
            font-weight: 600;
            cursor: pointer;
            margin-top: 16px;
            transition: all 0.2s;
        }}
        .copy-button:hover {{
            background: #2563eb;
            transform: translateY(-2px);
            box-shadow: 0 4px 12px rgba(59, 130, 246, 0.4);
        }}
        .copy-button:active {{
            transform: translateY(0);
        }}
        .copy-button.copied {{
            background: #10b981;
        }}
        .warning {{
            background: #fee2e2;
            border: 1px solid #fca5a5;
            border-radius: 8px;
            padding: 16px;
            margin-top: 24px;
            font-size: 14px;
            color: #991b1b;
        }}
        .next-steps {{
            text-align: left;
            margin-top: 32px;
            padding-top: 32px;
            border-top: 1px solid #e5e7eb;
        }}
        .next-steps h2 {{
            font-size: 18px;
            margin-bottom: 16px;
            color: #1f2937;
        }}
        .next-steps ol {{
            margin-left: 20px;
            color: #4b5563;
            line-height: 1.8;
        }}
        .next-steps code {{
            background: #f3f4f6;
            padding: 2px 6px;
            border-radius: 4px;
            font-family: 'Courier New', monospace;
            font-size: 13px;
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="success-icon">✓</div>
        <h1>Authentication Successful!</h1>
        <p>Your MCP API key has been created and linked to your GitHub account.</p>

        <div class="user-info">
            <strong>GitHub User:</strong> {username}<br>
            <strong>Created:</strong> {created_at}
        </div>

        <div class="token-container">
            <div class="token-label">Your MCP API Key</div>
            <div class="token-value" id="token">{mcp_key}</div>
            <button class="copy-button" onclick="copyToken()">Copy to Clipboard</button>
        </div>

        <div class="warning">
            <strong>⚠️ Important:</strong> This key will only be shown once.
            Please copy it now and store it securely.
        </div>

        <div class="next-steps">
            <h2>Next Steps</h2>
            <ol>
                <li>Copy your MCP API key using the button above</li>
                <li>Configure your MCP client with this key:
                    <br><code>Authorization: Bearer {mcp_key}</code>
                </li>
                <li>Start making requests to the MCP server</li>
                <li>Check the <a href="/docs" target="_blank">
                    API documentation</a> for available endpoints
                </li>
            </ol>
        </div>
    </div>

    <script>
        function copyToken() {{
            const token = document.getElementById('token').textContent;
            const button = document.querySelector('.copy-button');

            navigator.clipboard.writeText(token).then(() => {{
                button.textContent = '✓ Copied!';
                button.classList.add('copied');

                setTimeout(() => {{
                    button.textContent = 'Copy to Clipboard';
                    button.classList.remove('copied');
                }}, 2000);
            }});
        }}
    </script>
</body>
</html>
"""

ERROR_PAGE_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Authentication Error - MCP Server</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI',
                Roboto, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 20px;
        }}
        .container {{
            background: white;
            border-radius: 16px;
            box-shadow: 0 20px 60px rgba(0,0,0,0.3);
            max-width: 600px;
            width: 100%;
            padding: 40px;
            text-align: center;
        }}
        .error-icon {{
            width: 80px;
            height: 80px;
            background: #ef4444;
            border-radius: 50%;
            margin: 0 auto 24px;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 48px;
        }}
        h1 {{ color: #1f2937; margin-bottom: 16px; }}
        .error-message {{
            background: #fee2e2;
            border: 1px solid #fca5a5;
            border-radius: 8px;
            padding: 16px;
            margin: 24px 0;
            color: #991b1b;
        }}
        .retry-button {{
            background: #3b82f6;
            color: white;
            border: none;
            padding: 12px 24px;
            border-radius: 8px;
            font-size: 16px;
            font-weight: 600;
            cursor: pointer;
            margin-top: 16px;
            text-decoration: none;
            display: inline-block;
        }}
        .retry-button:hover {{
            background: #2563eb;
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="error-icon">✗</div>
        <h1>Authentication Failed</h1>
        <div class="error-message">
            <strong>Error:</strong> {error_message}
        </div>
        <a href="/auth/login" class="retry-button">Try Again</a>
    </div>
</body>
</html>
"""
