"""Command-line entry point for the GitHub PR Review MCP server."""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from importlib.metadata import version
from pathlib import Path

from dotenv import load_dotenv

from .server import PRReviewServer


@contextmanager
def _temporary_env_overrides(overrides: dict[str, int | None]) -> Iterator[None]:
    """Apply temporary environment variable overrides within a context."""
    previous_values: dict[str, str | None] = {}
    try:
        for key, value in overrides.items():
            if value is None:
                continue
            previous_values[key] = os.environ.get(key)
            os.environ[key] = str(value)
        yield
    finally:
        for key, previous in previous_values.items():
            if previous is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = previous


def _positive_int(value: str) -> int:
    try:
        ivalue = int(value)
    except ValueError as exc:  # pragma: no cover - argparse handles messaging
        raise argparse.ArgumentTypeError("must be an integer") from exc
    if ivalue <= 0:
        raise argparse.ArgumentTypeError("must be positive")
    return ivalue


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="mcp-github-pr-review",
        description="GitHub PR Review MCP server - supports stdio and HTTP streaming",
    )

    # Version flag
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {version('mcp-github-pr-review')}",
    )

    # Subcommands for different modes
    subparsers = parser.add_subparsers(dest="mode", help="Server mode")

    # stdio mode (default)
    stdio_parser = subparsers.add_parser(
        "stdio",
        help="Run server over stdio (default mode)",
    )
    stdio_parser.add_argument(
        "--env-file",
        type=Path,
        help="Optional path to a .env file to load before starting the server.",
    )
    stdio_parser.add_argument(
        "--max-pages",
        type=_positive_int,
        help="Override PR_FETCH_MAX_PAGES for this process.",
    )
    stdio_parser.add_argument(
        "--max-comments",
        type=_positive_int,
        help="Override PR_FETCH_MAX_COMMENTS for this process.",
    )
    stdio_parser.add_argument(
        "--per-page",
        type=_positive_int,
        help="Override HTTP_PER_PAGE for this process.",
    )
    stdio_parser.add_argument(
        "--max-retries",
        type=_positive_int,
        help="Override HTTP_MAX_RETRIES for this process.",
    )

    # http mode
    http_parser = subparsers.add_parser(
        "http",
        help="Run server over HTTP with streaming",
    )
    http_parser.add_argument(
        "--host",
        type=str,
        default="127.0.0.1",
        help="Host to bind to (default: 127.0.0.1)",
    )
    http_parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Port to bind to (default: 8000)",
    )
    http_parser.add_argument(
        "--env-file",
        type=Path,
        help="Optional path to a .env file to load before starting the server.",
    )
    http_parser.add_argument(
        "--max-pages",
        type=_positive_int,
        help="Override PR_FETCH_MAX_PAGES for this process.",
    )
    http_parser.add_argument(
        "--max-comments",
        type=_positive_int,
        help="Override PR_FETCH_MAX_COMMENTS for this process.",
    )
    http_parser.add_argument(
        "--per-page",
        type=_positive_int,
        help="Override HTTP_PER_PAGE for this process.",
    )
    http_parser.add_argument(
        "--max-retries",
        type=_positive_int,
        help="Override HTTP_MAX_RETRIES for this process.",
    )

    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    # Default to stdio mode if no subcommand specified
    mode = args.mode or "stdio"

    # Load environment file
    env_file = getattr(args, "env_file", None)
    if env_file:
        load_dotenv(env_file, override=True)
    else:
        load_dotenv(override=False)

    # Prepare environment overrides
    env_overrides = {
        "PR_FETCH_MAX_PAGES": getattr(args, "max_pages", None),
        "PR_FETCH_MAX_COMMENTS": getattr(args, "max_comments", None),
        "HTTP_PER_PAGE": getattr(args, "per_page", None),
        "HTTP_MAX_RETRIES": getattr(args, "max_retries", None),
    }

    server = PRReviewServer()
    try:
        with _temporary_env_overrides(env_overrides):
            if mode == "http":
                host = getattr(args, "host", "127.0.0.1")
                port = getattr(args, "port", 8000)
                asyncio.run(server.run_http(host=host, port=port))
            else:  # stdio mode
                asyncio.run(server.run())
    except KeyboardInterrupt:
        return 130
    except Exception:  # pragma: no cover - surfaces unexpected errors
        print("Unexpected server error", file=sys.stderr)
        raise
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
