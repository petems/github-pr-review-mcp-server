# Quickstart

Follow this quickstart to run the MCP server locally with `uv` in under ten minutes.

## Prerequisites

- Python 3.10 or later
- [`uv`](https://docs.astral.sh/uv/) package manager (recommended)
- GitHub personal access token with **read** access to pull requests

## Install and Run

```bash
# Clone the project
git clone https://github.com/cool-kids-inc/github-pr-review-mcp-server.git
cd github-pr-review-mcp-server

# Install runtime dependencies and the editable package
uv sync

# Provide credentials
echo "GITHUB_TOKEN=ghp_your_token" > .env

# Launch the MCP server over stdio
uv run mcp-github-pr-review
```

Once the server is running, connect it from your preferred MCP host (Claude Desktop, Codex CLI, Cursor, etc.).

## Register with Claude Code CLI

After installing, register the server with Claude Code:

```bash
# Install as a tool first
uv tool install mcp-github-pr-review

# Register with Claude Code CLI
claude mcp add pr-review --scope user --transport stdio --env GITHUB_TOKEN="${GITHUB_TOKEN}" -- \
  mcp-github-pr-review
```

**Command structure:**
- Server name (`pr-review`) comes FIRST
- All options (`--scope`, `--transport`, `--env`) come after server name but before `--`
- The `--` separator divides configuration from the command
- Command and arguments come after `--`

For other hosts (Cursor, VS Code, etc.), visit [Editor Integrations](../guides/editor-integrations.md).

## Verify a Connection

Use the built-in health command to ensure connectivity:

```bash
claude mcp call pr-review list-tools
```

Expected response includes `fetch_pr_review_comments` and `resolve_open_pr_url`.

## Next Steps

1. Review [Security Requirements](../security/index.md) before enabling automated agents.
2. Configure `PR_FETCH_MAX_*` environment limits if your repositories have high comment volume.
3. Explore [Remote Hosting with `uv`](../guides/remote-uv-endpoint.md) to serve the MCP process over TLS.
