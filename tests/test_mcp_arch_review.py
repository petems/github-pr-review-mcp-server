from typing import Any
from unittest.mock import AsyncMock

import pytest

from mcp_github_pr_review.errors import ToolExecutionError
from mcp_github_pr_review.models import (
    PaginatedReviewCommentsResult,
    ReviewCommentModel,
)
from mcp_github_pr_review.server import PRReviewServer


@pytest.mark.asyncio
async def test_handle_list_tools_includes_canonical_arch_review_tools(
    mcp_server: PRReviewServer,
) -> None:
    tools = await mcp_server.handle_list_tools()
    tools_by_name = {tool.name: tool for tool in tools}

    assert "github_list_pr_review_comments" in tools_by_name
    assert "github_resolve_open_pr_url" in tools_by_name

    list_tool = tools_by_name["github_list_pr_review_comments"]
    assert list_tool.annotations is not None
    assert list_tool.annotations.readOnlyHint is True
    assert list_tool.annotations.destructiveHint is False
    assert list_tool.annotations.idempotentHint is True
    assert list_tool.annotations.openWorldHint is True
    assert list_tool.outputSchema is not None
    assert "oneOf" in list_tool.outputSchema
    assert list_tool.inputSchema.get("additionalProperties") is False


@pytest.mark.asyncio
async def test_github_resolve_open_pr_url_returns_structured_output(
    monkeypatch: pytest.MonkeyPatch,
    mcp_server: PRReviewServer,
) -> None:
    resolve_mock = AsyncMock(return_value="https://github.com/o/r/pull/12")
    monkeypatch.setattr("mcp_github_pr_review.server.resolve_pr_url", resolve_mock)

    result = await mcp_server.handle_call_tool(
        "github_resolve_open_pr_url",
        {"owner": "o", "repo": "r", "branch": "feature"},
    )

    assert isinstance(result, tuple)
    content, structured = result
    assert content[0].type == "text"
    assert "Resolved open pull request URL" in content[0].text
    assert structured["url"] == "https://github.com/o/r/pull/12"


@pytest.mark.asyncio
async def test_github_list_pr_review_comments_returns_structured_output(
    monkeypatch: pytest.MonkeyPatch,
    mcp_server: PRReviewServer,
) -> None:
    paginated = PaginatedReviewCommentsResult(
        items=[
            ReviewCommentModel(
                user={"login": "alice"},
                path="src/app.py",
                line=42,
                body="Looks good",
            )
        ],
        nextCursor="cursor-token",
        total=1,
    )
    list_mock = AsyncMock(return_value=paginated)
    monkeypatch.setattr(mcp_server, "list_pr_review_comments", list_mock)

    result = await mcp_server.handle_call_tool(
        "github_list_pr_review_comments",
        {"pr_url": "https://github.com/o/r/pull/1", "limit": 10},
    )

    assert isinstance(result, tuple)
    content, structured = result
    assert content[0].type == "text"
    assert "Fetched 1 review comment" in content[0].text
    assert structured["total"] == 1
    assert structured["nextCursor"] == "cursor-token"
    assert len(structured["items"]) == 1

    kwargs = list_mock.await_args.kwargs
    assert kwargs["limit"] == 10
    assert kwargs["pr_url"] == "https://github.com/o/r/pull/1"


@pytest.mark.asyncio
async def test_github_list_pr_review_comments_returns_normalized_validation_error(
    mcp_server: PRReviewServer,
) -> None:
    result = await mcp_server.handle_call_tool(
        "github_list_pr_review_comments",
        {"limit": 0},
    )

    assert isinstance(result, tuple)
    content, structured = result
    assert content[0].type == "text"
    assert "Invalid argument" in content[0].text
    assert structured["error"]["code"] == "invalid_arguments"
    assert structured["error"]["next_steps"]


@pytest.mark.asyncio
async def test_github_list_pr_review_comments_rejects_unknown_fields(
    mcp_server: PRReviewServer,
) -> None:
    result = await mcp_server.handle_call_tool(
        "github_list_pr_review_comments",
        {"unexpectedField": "x"},
    )

    assert isinstance(result, tuple)
    _, structured = result
    assert structured["error"]["code"] == "invalid_arguments"


@pytest.mark.asyncio
async def test_github_list_pr_review_comments_returns_normalized_tool_error(
    monkeypatch: pytest.MonkeyPatch,
    mcp_server: PRReviewServer,
) -> None:
    async def fail(*args: Any, **kwargs: Any) -> PaginatedReviewCommentsResult:  # noqa: ARG001
        raise ToolExecutionError(
            code="auth",
            message="Authentication failed.",
            next_steps=["Set GITHUB_TOKEN and retry."],
        )

    monkeypatch.setattr(mcp_server, "list_pr_review_comments", fail)

    result = await mcp_server.handle_call_tool(
        "github_list_pr_review_comments",
        {"pr_url": "https://github.com/o/r/pull/1"},
    )

    assert isinstance(result, tuple)
    content, structured = result
    assert content[0].text == "Authentication failed."
    assert structured["error"]["code"] == "auth"
    assert structured["error"]["next_steps"] == ["Set GITHUB_TOKEN and retry."]
