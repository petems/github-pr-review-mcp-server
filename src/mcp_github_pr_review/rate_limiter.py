"""Rate limiting implementation for MCP HTTP server.

This module provides per-user rate limiting using a sliding window algorithm
with in-memory storage. The implementation is designed to be upgraded to Redis
for distributed rate limiting across multiple server instances.

Algorithm:
    - Sliding window: Tracks request timestamps in a time window
    - Automatic cleanup: Removes expired entries to prevent memory leaks
    - Burst allowance: Allows short bursts above the sustained rate

Security Considerations:
    - Rate limits are per MCP API key
    - Prevents abuse and resource exhaustion
    - Configurable limits via environment variables
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Protocol

logger = logging.getLogger(__name__)


@dataclass
class RateLimitInfo:
    """Information about a rate limit check.

    Attributes:
        allowed: Whether the request is allowed
        limit: Maximum requests per window
        remaining: Remaining requests in current window
        reset_at: Timestamp when the limit resets (Unix time)
        retry_after: Seconds to wait before retrying (if not allowed)
    """

    allowed: bool
    limit: int
    remaining: int
    reset_at: float
    retry_after: float = 0.0


@dataclass
class RateLimitBucket:
    """Tracks request history for a single user/key.

    Uses a deque to store request timestamps and automatically
    removes expired entries during checks.

    Attributes:
        requests: Deque of request timestamps (Unix time)
        window_seconds: Time window for rate limiting (default: 60)
        created_at: When this bucket was created
    """

    requests: deque[float] = field(default_factory=deque)
    window_seconds: int = 60
    created_at: float = field(default_factory=time.time)

    def add_request(self, timestamp: float | None = None) -> None:
        """Add a request to the bucket.

        Args:
            timestamp: Request timestamp (default: current time)
        """
        if timestamp is None:
            timestamp = time.time()
        self.requests.append(timestamp)

    def cleanup_expired(self, current_time: float | None = None) -> None:
        """Remove expired requests from the bucket.

        Args:
            current_time: Current timestamp (default: time.time())
        """
        if current_time is None:
            current_time = time.time()

        cutoff = current_time - self.window_seconds

        # Remove all requests older than the window
        while self.requests and self.requests[0] < cutoff:
            self.requests.popleft()

    def count_requests(self, current_time: float | None = None) -> int:
        """Count requests in the current window.

        Args:
            current_time: Current timestamp (default: time.time())

        Returns:
            Number of requests in the current window
        """
        self.cleanup_expired(current_time)
        return len(self.requests)

    def get_oldest_request(self) -> float | None:
        """Get the timestamp of the oldest request in the window.

        Returns:
            Timestamp of oldest request, or None if empty
        """
        return self.requests[0] if self.requests else None


class RateLimiter(Protocol):
    """Protocol defining the rate limiter interface."""

    async def check_limit(
        self,
        key: str,
        limit: int,
        window_seconds: int,
        burst: int = 0,
    ) -> RateLimitInfo:
        """Check if a request is allowed under the rate limit.

        Args:
            key: Identifier for rate limiting (e.g., MCP API key)
            limit: Maximum requests per window
            window_seconds: Time window in seconds
            burst: Additional burst allowance

        Returns:
            RateLimitInfo with decision and metadata
        """
        ...

    async def reset_limit(self, key: str) -> None:
        """Reset rate limit for a key.

        Args:
            key: Identifier to reset
        """
        ...


class InMemoryRateLimiter:
    """In-memory implementation of rate limiting using sliding window.

    This implementation stores request histories in memory using deques.
    For production use with multiple instances, consider using Redis.

    The sliding window algorithm accurately tracks requests over time,
    providing smooth rate limiting without the "burst at window edge"
    problem of fixed windows.
    """

    def __init__(self, cleanup_interval: int = 300) -> None:
        """Initialize the in-memory rate limiter.

        Args:
            cleanup_interval: Seconds between automatic cleanup runs
        """
        self._buckets: dict[str, RateLimitBucket] = {}
        self._lock = asyncio.Lock()
        self._cleanup_interval = cleanup_interval
        self._cleanup_task: asyncio.Task[None] | None = None
        logger.info(
            "Initialized in-memory rate limiter",
            extra={"cleanup_interval": cleanup_interval},
        )

    async def start(self) -> None:
        """Start the background cleanup task."""
        if self._cleanup_task is None:
            self._cleanup_task = asyncio.create_task(self._cleanup_loop())
            logger.info("Started rate limiter cleanup task")

    async def stop(self) -> None:
        """Stop the background cleanup task."""
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
            self._cleanup_task = None
            logger.info("Stopped rate limiter cleanup task")

    async def _cleanup_loop(self) -> None:
        """Background task to clean up empty buckets."""
        while True:
            try:
                await asyncio.sleep(self._cleanup_interval)
                await self._cleanup_empty_buckets()
            except asyncio.CancelledError:
                break
            except Exception:  # noqa: BLE001
                logger.exception("Error in rate limiter cleanup")

    async def _cleanup_empty_buckets(self) -> None:
        """Remove buckets with no recent requests."""
        async with self._lock:
            current_time = time.time()
            keys_to_remove = []

            for key, bucket in self._buckets.items():
                bucket.cleanup_expired(current_time)
                if len(bucket.requests) == 0:
                    keys_to_remove.append(key)

            for key in keys_to_remove:
                del self._buckets[key]

            if keys_to_remove:
                logger.debug(
                    "Cleaned up empty rate limit buckets",
                    extra={"count": len(keys_to_remove)},
                )

    async def check_limit(
        self,
        key: str,
        limit: int,
        window_seconds: int,
        burst: int = 0,
    ) -> RateLimitInfo:
        """Check if a request is allowed under the rate limit.

        Args:
            key: Identifier for rate limiting (e.g., MCP API key)
            limit: Maximum requests per window
            window_seconds: Time window in seconds
            burst: Additional burst allowance

        Returns:
            RateLimitInfo with decision and metadata
        """
        async with self._lock:
            current_time = time.time()

            # Get or create bucket for this key
            if key not in self._buckets:
                self._buckets[key] = RateLimitBucket(window_seconds=window_seconds)

            bucket = self._buckets[key]

            # Update window if changed
            if bucket.window_seconds != window_seconds:
                bucket.window_seconds = window_seconds

            # Count requests in current window
            request_count = bucket.count_requests(current_time)

            # Calculate effective limit with burst
            effective_limit = limit + burst

            # Check if request is allowed
            allowed = request_count < effective_limit

            if allowed:
                # Record this request
                bucket.add_request(current_time)
                remaining = effective_limit - request_count - 1
            else:
                remaining = 0

            # Calculate when the limit resets (when oldest request expires)
            oldest_request = bucket.get_oldest_request()
            if oldest_request:
                reset_at = oldest_request + window_seconds
                retry_after = max(0.0, reset_at - current_time)
            else:
                reset_at = current_time + window_seconds
                retry_after = 0.0

            result = RateLimitInfo(
                allowed=allowed,
                limit=effective_limit,
                remaining=max(0, remaining),
                reset_at=reset_at,
                retry_after=retry_after,
            )

            if not allowed:
                logger.warning(
                    "Rate limit exceeded",
                    extra={
                        "key_prefix": key[:8] + "..." if len(key) > 8 else key,
                        "request_count": request_count,
                        "limit": effective_limit,
                        "retry_after": retry_after,
                    },
                )

            return result

    async def reset_limit(self, key: str) -> None:
        """Reset rate limit for a key.

        Args:
            key: Identifier to reset
        """
        async with self._lock:
            if key in self._buckets:
                del self._buckets[key]
                logger.info(
                    "Reset rate limit",
                    extra={"key_prefix": key[:8] + "..." if len(key) > 8 else key},
                )

    async def get_bucket_count(self) -> int:
        """Get the number of active rate limit buckets.

        Returns:
            Number of buckets
        """
        async with self._lock:
            return len(self._buckets)


# Global instance for easy access
_global_limiter: InMemoryRateLimiter | None = None


def get_rate_limiter() -> InMemoryRateLimiter:
    """Get or create the global rate limiter instance.

    Returns:
        The global InMemoryRateLimiter instance
    """
    global _global_limiter
    if _global_limiter is None:
        _global_limiter = InMemoryRateLimiter()
    return _global_limiter
