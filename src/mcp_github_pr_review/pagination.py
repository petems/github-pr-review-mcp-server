"""Cursor helpers for paginated MCP tool responses."""

from __future__ import annotations

import base64


def encode_cursor(next_url: str) -> str:
    """Encode a URL cursor into a compact transport-safe string."""
    cursor = base64.urlsafe_b64encode(next_url.encode("utf-8"))
    return cursor.decode("ascii")


def decode_cursor(cursor: str) -> str:
    """Decode a previously encoded cursor URL."""
    try:
        decoded = base64.urlsafe_b64decode(cursor.encode("ascii")).decode("utf-8")
    except (ValueError, UnicodeDecodeError) as exc:
        raise ValueError("Invalid pagination cursor") from exc
    if not decoded.startswith("http://") and not decoded.startswith("https://"):
        raise ValueError("Invalid pagination cursor")
    return decoded
