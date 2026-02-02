"""Tests specifically targeting coverage gaps identified by coverage report."""

import pytest
from conftest import DummyResp, FakeClient

from mcp_github_pr_review.git_pr_resolver import resolve_pr_url


@pytest.mark.asyncio
async def test_resolve_pr_url_error_strategy_no_pr(monkeypatch):
    """Test error strategy when GraphQL finds no PR."""

    class EmptyResultClient(FakeClient):
        async def get(self, url, headers=None):
            # Return empty for both GraphQL and REST
            return DummyResp([])

    monkeypatch.setattr(
        "mcp_github_pr_review.git_pr_resolver.httpx.AsyncClient",
        lambda *a, **k: EmptyResultClient(*a, **k),
    )

    # Should raise ValueError when no PR found and error strategy
    with pytest.raises(ValueError, match="No open PR found"):
        await resolve_pr_url("o", "r", branch="test", select_strategy="error")


@pytest.mark.asyncio
async def test_resolve_pr_url_branch_strategy_requires_branch(monkeypatch):
    """Test branch strategy requires branch parameter."""

    class SomePRsClient(FakeClient):
        async def get(self, url, headers=None):
            if "graphql" in url:
                return DummyResp([])
            return DummyResp(
                [
                    {
                        "html_url": "https://github.com/o/r/pull/1",
                        "number": 1,
                        "head": {"ref": "some-branch"},
                    }
                ]
            )

    monkeypatch.setattr(
        "mcp_github_pr_review.git_pr_resolver.httpx.AsyncClient",
        lambda *a, **k: SomePRsClient(*a, **k),
    )

    # Should raise ValueError when branch is None with branch strategy
    with pytest.raises(ValueError, match="Branch strategy requires a branch name"):
        await resolve_pr_url("o", "r", branch=None, select_strategy="branch")
