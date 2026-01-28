# HTTP Transport

The MCP server supports HTTP transport for remote access, in addition to the default stdio transport.

## Quick Start

**Start HTTP server:**
```bash
# Default (127.0.0.1:8000)
uv run mcp-github-pr-review --http

# Custom host/port
uv run mcp-github-pr-review --http 0.0.0.0:3000
```

## Client Configuration

### Claude Code

Add to your MCP settings JSON:

```json
{
  "mcpServers": {
    "github-pr-review": {
      "url": "http://127.0.0.1:8000",
      "transport": "http"
    }
  }
}
```

### OpenAI Codex

Add to `~/.codex/config.toml`:

```toml
[mcp_servers.github-pr-review]
url = "http://127.0.0.1:8000"
```

## Authentication

The server uses a GitHub token from its environment (`GITHUB_TOKEN`). All client requests use this server-side token transparently - no client-side GitHub authentication is required.

Set the token before starting the server:

```bash
export GITHUB_TOKEN="your_github_token_here"
uv run mcp-github-pr-review --http
```

## Technical Details

- **Protocol**: MCP over HTTP with JSON-RPC
- **Transport**: `StreamableHTTPServerTransport` with JSON responses
- **Method**: HTTP POST requests only
- **Content-Type**: `application/json`
- **Accept Header**: `application/json, text/event-stream` (required by MCP spec)

Note: Despite the Accept header including `text/event-stream`, the server returns JSON responses only. This header is required for MCP protocol compatibility.
