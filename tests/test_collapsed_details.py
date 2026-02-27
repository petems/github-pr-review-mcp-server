"""Tests for collapsed <details> sanitization in comment bodies."""

from mcp_github_pr_review.server import (
    _sanitize_comment_bodies,
    _strip_collapsed_details,
)


def test_strip_collapsed_details_with_summary() -> None:
    body = (
        "Visible\n"
        "<details><summary>Expandable context</summary>\n"
        "hidden content\n"
        "</details>\n"
        "Tail"
    )
    sanitized, had_fold = _strip_collapsed_details(body)
    assert had_fold is True
    assert "hidden content" not in sanitized
    assert "Expandable context" in sanitized
    assert "[Folded details omitted]" in sanitized
    assert "Visible" in sanitized and "Tail" in sanitized


def test_strip_collapsed_details_without_summary() -> None:
    body = "A<details>hidden only</details>B"
    sanitized, had_fold = _strip_collapsed_details(body)
    assert had_fold is True
    assert sanitized == "A[Folded details omitted]B"


def test_strip_collapsed_details_multiple_blocks() -> None:
    body = (
        "Start "
        "<details><summary>One</summary>hidden-1</details> "
        "Middle "
        "<details><summary>Two</summary>hidden-2</details> "
        "End"
    )
    sanitized, had_fold = _strip_collapsed_details(body)
    assert had_fold is True
    assert "hidden-1" not in sanitized
    assert "hidden-2" not in sanitized
    assert sanitized.count("[Folded details omitted]") == 2
    assert "One" in sanitized and "Two" in sanitized


def test_strip_collapsed_details_nested_blocks() -> None:
    body = (
        "<details><summary>Outer summary</summary>\n"
        "outer hidden\n"
        "<details><summary>Inner summary</summary>inner hidden</details>\n"
        "</details>"
    )
    sanitized, had_fold = _strip_collapsed_details(body)
    assert had_fold is True
    assert sanitized == "Outer summary\n[Folded details omitted]"


def test_strip_collapsed_details_unclosed_block() -> None:
    body = "Prefix <details><summary>Unclosed summary</summary>hidden forever"
    sanitized, had_fold = _strip_collapsed_details(body)
    assert had_fold is True
    assert "hidden forever" not in sanitized
    assert sanitized.endswith("Unclosed summary\n[Folded details omitted]")


def test_strip_collapsed_details_mixed_content() -> None:
    body = (
        "Intro text\n"
        "- bullet 1\n"
        "<details><summary>Verbose logs</summary>\n"
        "line a\n"
        "line b\n"
        "</details>\n"
        "- bullet 2"
    )
    sanitized, had_fold = _strip_collapsed_details(body)
    assert had_fold is True
    assert "Intro text" in sanitized
    assert "- bullet 2" in sanitized
    assert "Verbose logs" in sanitized
    assert "line a" not in sanitized


def test_sanitize_comment_bodies_respects_flag() -> None:
    comments = [
        {
            "id": 1,
            "body": "<details><summary>Summary</summary>hidden</details>",
            "user": {"login": "bot"},
        }
    ]
    sanitized_default = _sanitize_comment_bodies(
        comments, include_collapsed_details=False
    )
    sanitized_opt_out = _sanitize_comment_bodies(
        comments, include_collapsed_details=True
    )

    assert "hidden" not in sanitized_default[0]["body"]
    assert "[Folded details omitted]" in sanitized_default[0]["body"]
    assert sanitized_opt_out[0]["body"] == comments[0]["body"]
