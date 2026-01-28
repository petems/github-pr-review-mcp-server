"""Token storage abstraction for MCP API keys and GitHub tokens.

This module provides an in-memory token storage system that maps MCP API keys
to GitHub Personal Access Tokens. The interface is designed to support future
migration to Redis or other persistent storage backends.

Security Considerations:
    - Tokens are stored in memory only and lost on restart
    - No encryption at rest (suitable for development/testing)
    - Thread-safe operations using asyncio locks
    - For production, consider persistent encrypted storage
"""

from __future__ import annotations

import asyncio
import logging
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Protocol

logger = logging.getLogger(__name__)


@dataclass
class TokenMapping:
    """Represents a mapping between an MCP API key and a GitHub token.

    Attributes:
        mcp_key: The MCP API key (public identifier)
        github_token: The GitHub Personal Access Token
        created_at: When this mapping was created
        last_used_at: When this mapping was last accessed
        user_id: Optional user identifier for auditing
        description: Optional human-readable description
    """

    mcp_key: str
    github_token: str
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    last_used_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    user_id: str | None = None
    description: str | None = None

    def touch(self) -> None:
        """Update the last_used_at timestamp."""
        self.last_used_at = datetime.now(timezone.utc)


class TokenStore(Protocol):
    """Protocol defining the token storage interface.

    This protocol allows different storage backends (in-memory, Redis, etc.)
    to be used interchangeably.
    """

    async def store_token(
        self,
        mcp_key: str,
        github_token: str,
        *,
        user_id: str | None = None,
        description: str | None = None,
    ) -> None:
        """Store a mapping between MCP API key and GitHub token.

        Args:
            mcp_key: The MCP API key
            github_token: The GitHub Personal Access Token
            user_id: Optional user identifier
            description: Optional description
        """
        ...

    async def get_github_token(self, mcp_key: str) -> str | None:
        """Retrieve GitHub token for an MCP API key.

        Args:
            mcp_key: The MCP API key to look up

        Returns:
            GitHub token if found, None otherwise
        """
        ...

    async def get_mapping(self, mcp_key: str) -> TokenMapping | None:
        """Retrieve full token mapping for an MCP API key.

        Args:
            mcp_key: The MCP API key to look up

        Returns:
            TokenMapping if found, None otherwise
        """
        ...

    async def delete_token(self, mcp_key: str) -> bool:
        """Delete a token mapping.

        Args:
            mcp_key: The MCP API key to delete

        Returns:
            True if deleted, False if not found
        """
        ...

    async def list_tokens(self) -> list[TokenMapping]:
        """List all token mappings (for admin purposes).

        Returns:
            List of all token mappings
        """
        ...

    async def exists(self, mcp_key: str) -> bool:
        """Check if an MCP API key exists.

        Args:
            mcp_key: The MCP API key to check

        Returns:
            True if exists, False otherwise
        """
        ...


class InMemoryTokenStore:
    """In-memory implementation of TokenStore.

    This implementation stores tokens in a dictionary with asyncio locking
    for thread safety. Tokens are lost on server restart.

    For production use with multiple instances, consider using Redis or
    another distributed cache.
    """

    def __init__(self) -> None:
        """Initialize the in-memory token store."""
        self._store: dict[str, TokenMapping] = {}
        self._lock = asyncio.Lock()
        logger.info("Initialized in-memory token store")

    async def store_token(
        self,
        mcp_key: str,
        github_token: str,
        *,
        user_id: str | None = None,
        description: str | None = None,
    ) -> None:
        """Store a mapping between MCP API key and GitHub token.

        Args:
            mcp_key: The MCP API key
            github_token: The GitHub Personal Access Token
            user_id: Optional user identifier
            description: Optional description
        """
        async with self._lock:
            mapping = TokenMapping(
                mcp_key=mcp_key,
                github_token=github_token,
                user_id=user_id,
                description=description,
            )
            self._store[mcp_key] = mapping
            logger.info(
                "Stored token mapping",
                extra={
                    "mcp_key_prefix": mcp_key[:8] + "...",
                    "user_id": user_id,
                    "description": description,
                },
            )

    async def get_github_token(self, mcp_key: str) -> str | None:
        """Retrieve GitHub token for an MCP API key.

        Args:
            mcp_key: The MCP API key to look up

        Returns:
            GitHub token if found, None otherwise
        """
        async with self._lock:
            mapping = self._store.get(mcp_key)
            if mapping:
                mapping.touch()
                logger.debug(
                    "Retrieved GitHub token",
                    extra={"mcp_key_prefix": mcp_key[:8] + "..."},
                )
                return mapping.github_token
            logger.debug(
                "GitHub token not found",
                extra={"mcp_key_prefix": mcp_key[:8] + "..."},
            )
            return None

    async def get_mapping(self, mcp_key: str) -> TokenMapping | None:
        """Retrieve full token mapping for an MCP API key.

        Args:
            mcp_key: The MCP API key to look up

        Returns:
            TokenMapping if found, None otherwise
        """
        async with self._lock:
            mapping = self._store.get(mcp_key)
            if mapping:
                mapping.touch()
            return mapping

    async def delete_token(self, mcp_key: str) -> bool:
        """Delete a token mapping.

        Args:
            mcp_key: The MCP API key to delete

        Returns:
            True if deleted, False if not found
        """
        async with self._lock:
            if mcp_key in self._store:
                del self._store[mcp_key]
                logger.info(
                    "Deleted token mapping",
                    extra={"mcp_key_prefix": mcp_key[:8] + "..."},
                )
                return True
            return False

    async def list_tokens(self) -> list[TokenMapping]:
        """List all token mappings (for admin purposes).

        Returns:
            List of all token mappings (copies to prevent external mutation)
        """
        async with self._lock:
            # Return copies to prevent external mutation
            return [
                TokenMapping(
                    mcp_key=m.mcp_key,
                    github_token=m.github_token,
                    created_at=m.created_at,
                    last_used_at=m.last_used_at,
                    user_id=m.user_id,
                    description=m.description,
                )
                for m in self._store.values()
            ]

    async def exists(self, mcp_key: str) -> bool:
        """Check if an MCP API key exists.

        Args:
            mcp_key: The MCP API key to check

        Returns:
            True if exists, False otherwise
        """
        async with self._lock:
            return mcp_key in self._store

    async def count(self) -> int:
        """Get the total number of stored tokens.

        Returns:
            Number of token mappings
        """
        async with self._lock:
            return len(self._store)


def generate_mcp_key(prefix: str = "mcp") -> str:
    """Generate a secure random MCP API key.

    Args:
        prefix: Prefix for the key (default: "mcp")

    Returns:
        A URL-safe random key with the specified prefix

    Example:
        >>> key = generate_mcp_key()
        >>> key.startswith("mcp_")
        True
        >>> len(key) > 40
        True
    """
    # Generate 32 bytes of random data (256 bits)
    random_bytes = secrets.token_urlsafe(32)
    return f"{prefix}_{random_bytes}"


# Global instance for easy access
_global_store: InMemoryTokenStore | None = None


def get_token_store() -> InMemoryTokenStore:
    """Get or create the global token store instance.

    Returns:
        The global InMemoryTokenStore instance
    """
    global _global_store
    if _global_store is None:
        _global_store = InMemoryTokenStore()
    return _global_store
