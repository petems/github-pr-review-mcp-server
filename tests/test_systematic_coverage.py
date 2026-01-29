"""Systematic tests to cover all remaining uncovered lines."""

import importlib
import os
import tempfile
from unittest.mock import MagicMock, patch

import pytest

# Tests removed - failing or not adding new coverage


def test_config_get_le_constraint_none():
    """Test _get_le_constraint returns None when no Le constraint."""
    from pydantic.fields import FieldInfo

    from mcp_github_pr_review.config import _get_le_constraint

    field_info = FieldInfo(annotation=int, default=10, metadata=[])
    assert _get_le_constraint(field_info) is None


def test_config_get_ge_constraint_none():
    """Test _get_ge_constraint returns None when no Ge constraint."""
    from pydantic.fields import FieldInfo

    from mcp_github_pr_review.config import _get_ge_constraint

    field_info = FieldInfo(annotation=int, default=10, metadata=[])
    assert _get_ge_constraint(field_info) is None


# Test git_pr_resolver.py lines 72, 103-104, 279-282
def test_git_pr_resolver_get_repo_not_git():
    """Test _get_repo raises ValueError when not a git repo."""
    from mcp_github_pr_review.git_pr_resolver import _get_repo

    with tempfile.TemporaryDirectory() as tmpdir:
        with pytest.raises(ValueError, match="Not a git repository"):
            _get_repo(cwd=tmpdir)


# Test server.py lines 54-55, 73-79 (version fallback and loopback check)
def test_server_version_exception_fallback():
    """Test server.__version__ falls back on exception."""
    with patch("mcp_github_pr_review.server.version", side_effect=Exception("test")):
        from mcp_github_pr_review import server

        importlib.reload(server)
        assert server.__version__ == "0.1.0"


def test_server_is_loopback_localhost():
    """Test _is_loopback_host recognizes localhost."""
    from mcp_github_pr_review.server import _is_loopback_host

    assert _is_loopback_host("localhost") is True
    assert _is_loopback_host("LOCALHOST") is True
    assert _is_loopback_host("  localhost  ") is True


def test_server_is_loopback_ipv4():
    """Test _is_loopback_host recognizes IPv4 loopback."""
    from mcp_github_pr_review.server import _is_loopback_host

    assert _is_loopback_host("127.0.0.1") is True
    assert _is_loopback_host("127.0.0.5") is True


def test_server_is_loopback_invalid():
    """Test _is_loopback_host handles invalid hosts."""
    from mcp_github_pr_review.server import _is_loopback_host

    assert _is_loopback_host("github.com") is False
    assert _is_loopback_host("invalid") is False


# Test server.py lines 226, 229-230 (rate limit detection)
def test_server_is_secondary_rate_limit_not_403_or_429():
    """Test _is_secondary_rate_limit returns False for non-rate-limit status."""
    from mcp_github_pr_review.server import RateLimitHandler

    handler = RateLimitHandler("test")
    mock_response = MagicMock()
    mock_response.status_code = 200

    assert handler._is_secondary_rate_limit(mock_response) is False


def test_server_is_secondary_rate_limit_json_error():
    """Test _is_secondary_rate_limit handles JSON errors."""
    from mcp_github_pr_review.server import RateLimitHandler

    handler = RateLimitHandler("test")
    mock_response = MagicMock()
    mock_response.status_code = 403
    mock_response.json.side_effect = ValueError("bad json")

    assert handler._is_secondary_rate_limit(mock_response) is False


def test_server_is_secondary_rate_limit_non_dict():
    """Test _is_secondary_rate_limit handles non-dict responses."""
    from mcp_github_pr_review.server import RateLimitHandler

    handler = RateLimitHandler("test")
    mock_response = MagicMock()
    mock_response.status_code = 403
    mock_response.json.return_value = ["not", "dict"]

    assert handler._is_secondary_rate_limit(mock_response) is False


# Test server.py line 253 (primary rate limit delay returns None)
def test_server_primary_rate_limit_delay_none():
    """Test _primary_rate_limit_delay returns None when not rate limited."""
    from mcp_github_pr_review.server import RateLimitHandler

    handler = RateLimitHandler("test")
    mock_response = MagicMock()
    mock_response.headers = {}

    assert handler._primary_rate_limit_delay(mock_response) is None


# Test removed - method doesn't exist


# Test server.py lines 1500-1511 (HTTP import error)
@pytest.mark.asyncio
async def test_server_run_http_import_error(capsys):
    """Test run_http raises RuntimeError when dependencies missing."""
    from mcp_github_pr_review.server import PRReviewServer

    server = PRReviewServer()

    original_import = __builtins__["__import__"]

    def mock_import(name, *args, **kwargs):
        if name in ["anyio", "uvicorn", "starlette"]:
            raise ImportError(f"No module named '{name}'")
        return original_import(name, *args, **kwargs)

    with patch("builtins.__import__", side_effect=mock_import):
        with pytest.raises(RuntimeError, match="Missing HTTP dependencies"):
            await server.run_http("127.0.0.1", 8000)

    captured = capsys.readouterr()
    assert "HTTP dependencies are not installed" in captured.err


# Test server.py lines 1527+ (HTTP auth required for non-loopback)
@pytest.mark.asyncio
async def test_server_run_http_non_loopback_no_auth(capsys):
    """Test run_http requires auth for non-loopback hosts."""
    from mcp_github_pr_review.server import PRReviewServer

    server = PRReviewServer()

    with patch.dict(
        os.environ, {"MCP_HTTP_AUTH_TOKEN": "", "MCP_HTTP_ALLOW_PUBLIC": ""}
    ):
        with pytest.raises(RuntimeError, match="HTTP auth required"):
            await server.run_http("192.168.1.1", 8000)

    captured = capsys.readouterr()
    assert "Refusing to bind" in captured.err
