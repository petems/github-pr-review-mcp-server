# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

> **⚠️ Security Notice**: Please review [SECURITY.md](SECURITY.md) for important security considerations, particularly regarding agentic workflows and the security implications of implementing PR comments automatically.

## 🚨 CRITICAL: NO SSE - HTTP STREAMING ONLY 🚨

**ABSOLUTE RULE: This project uses HTTP STREAMING, NOT SSE (Server-Sent Events).**

### Why No SSE?

**Reference:** [Why MCP deprecated SSE and went with streamable HTTP](https://blog.fka.dev/blog/2025-06-06-why-mcp-deprecated-sse-and-go-with-streamable-http/?ref=blog.globalping.io)

**Key reasons:**
- SSE is unreliable and problematic in production
- HTTP streaming with JSON is more robust and widely supported
- MCP protocol moved away from SSE for good architectural reasons
- This project follows best practices by using `StreamableHTTPServerTransport` with JSON mode

### Communication Guidelines

- When discussing the HTTP mode, ONLY mention "HTTP streaming" or "StreamableHTTPServerTransport"
- NEVER mention "SSE", "Server-Sent Events", or "EventSource" as features we use
- The `Accept: application/json, text/event-stream` header is required by MCP protocol but we use JSON responses only
- Focus on HTTP POST requests with JSON-RPC and JSON responses
- This is HTTP streaming with JSON, NOT event streaming

## Development Commands

This project uses `uv` as the primary package manager for fast, reproducible development:

```bash
# Install all dependencies (production + development)
uv sync --dev

# Run linting and auto-fix
uv run ruff check --fix .

# Format code
uv run ruff format .

# Check formatting (without making changes)
uv run ruff format --check .

# Static type check
uv run mypy .

# Run tests
uv run pytest

# Run tests with verbose output
uv run pytest -v

# Run a specific test file
uv run pytest tests/test_git_pr_resolver.py -v

# Syntax compile check (fail fast on SyntaxError)
make compile-check

# Run the MCP server
uv run mcp-github-pr-review

# Pre-commit quality check (format, lint, type, syntax, test)
uv run ruff format . && uv run ruff check --fix . && uv run mypy . && make compile-check && uv run pytest

# Check formatting compliance (CI/validation)
uv run ruff format --check . && uv run ruff check . && uv run mypy . && make compile-check && uv run pytest
```

## Architecture Overview

This is a Model Context Protocol (MCP) server that provides tools for fetching and formatting GitHub PR review comments with resolution status and diff context.

### Core Components

- **`PRReviewServer` class**: Main MCP server class that handles tool registration and execution
- **`fetch_pr_comments()` async function**: Core GitHub API integration with pagination, error handling, and retry logic
- **`generate_markdown()` function**: Converts review comments to formatted markdown with dynamic code fencing
- **`get_pr_info()` function**: URL parser for extracting owner/repo/PR number from GitHub URLs

### Key Architecture Patterns

- **Async/await throughout**: All GitHub API calls are async
- **Robust error handling**: Network timeouts, API errors, and rate limiting are handled gracefully
- **Configuration via environment**: Uses `.env` file loading with sensible defaults
- **Pagination safety**: Built-in limits prevent runaway API calls (max pages/comments)
- **Dynamic markdown fencing**: Automatically adjusts code block fencing to handle nested backticks

### MCP Tools Exposed

1. **`fetch_pr_review_comments`**: Fetches all review comments from a GitHub PR URL with configurable pagination and safety limits, returning formatted markdown by default (or JSON/both)
2. **`resolve_open_pr_url`**: Resolves the open PR URL for the current branch using git detection

### Environment Configuration

Required: `GITHUB_TOKEN` (GitHub PAT with appropriate repo access)

**Enterprise GitHub Variables**:
- `GH_HOST` (default "github.com"): GitHub hostname for enterprise installations
- `GITHUB_API_URL` (optional): Explicit REST API base URL override
- `GITHUB_GRAPHQL_URL` (optional): Explicit GraphQL API URL override

Optional tuning parameters:
- `PR_FETCH_MAX_PAGES` (default 50): Safety limit on pagination
- `PR_FETCH_MAX_COMMENTS` (default 2000): Safety limit on total comments
- `HTTP_PER_PAGE` (default 100): GitHub API page size
- `HTTP_MAX_RETRIES` (default 3): Retry limit for transient errors

### File Structure

- `src/mcp_github_pr_review/server.py`: Main server implementation
- `tests/`: Consolidated pytest suite and fixtures
  - `tests/conftest.py`: Common fixtures (HTTP client mock, git context, temp dirs, timeouts)
  - `tests/test_git_pr_resolver.py`: Unit tests for PR resolution utilities
  - `tests/test_integration.py`: End-to-end and integration tests (token-gated)
  - `tests/test_pagination_limits.py`: Pagination and safety cap tests
- `pyproject.toml`: Project configuration with Ruff and pytest
- `AGENTS.md`: Agent-specific workflow documentation
- `UV_COMMANDS.md`: Quick reference for uv commands

## Testing

Pytest is the single test runner, with async tests and shared fixtures under `tests/conftest.py`. Avoid live GitHub calls by default; integration tests are token-gated and may skip.

```bash
# Run all tests
uv run pytest -q

# Run with coverage (if pytest-cov is installed)
uv run pytest --cov=. --cov-report=html

# Run a focused test
uv run pytest tests/test_pagination_limits.py -q
```

## Code Quality

Ruff is configured for comprehensive linting and formatting:
- Line length: 88 characters
- Targets Python 3.10+
- Includes security (bandit), import sorting, and modern Python practices
- Auto-fix enabled for most issues

## Development Workflow

**CRITICAL**: After implementing any feature or fixing bugs, ALWAYS run the full quality check pipeline:

```bash
# Required before pushing any code changes
uv run ruff format . && uv run ruff check --fix . && uv run mypy . && make compile-check && uv run pytest
```

This ensures:
1. Code is properly formatted (ruff format)
2. All linting issues are resolved (ruff check --fix)
3. Static typing is validated (mypy)
4. Syntax is valid (make compile-check)
5. All unit tests pass (pytest)

For CI/validation without making changes, use:
```bash
uv run ruff format --check . && uv run ruff check . && uv run mypy . && make compile-check && uv run pytest
```

**Never push code without running these commands first.** The pipeline must pass completely before any git push operation.
- Use caplog for testing logging
- Use proper logging, not print statements