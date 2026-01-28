# Multi-Tenant Token Architecture

## Current Behavior (Single Token)

The server uses a single `GITHUB_TOKEN` from its environment for all requests:
- Simple deployment model
- All users share the same GitHub API rate limits
- Works well for personal use or team servers

## Per-User Token Architecture (Future)

To support per-user GitHub tokens where each client provides their own token:

### Option 1: MCP OAuth Pass-Through

```python
# Server receives client's OAuth token via MCP auth
async def fetch_pr_comments_with_client_token(
    owner: str,
    repo: str,
    pull_number: int,
    *,
    client_token: str | None = None,  # From MCP OAuth
    host: str = "github.com",
) -> list[CommentResult] | None:
    # Priority: client token > server token
    token = client_token or os.getenv("GITHUB_TOKEN")
    if not token:
        logger.error("GitHub token required (from client or server)")
        return None

    headers = {
        "Authorization": f"Bearer {token}",
        # ...
    }
```

### Option 2: Custom Header

```python
# Client passes GitHub token in custom header
# MCP server extracts it from request context

async def mcp_endpoint(scope, receive, send):
    # Extract GitHub token from X-GitHub-Token header
    github_token = None
    for header, value in scope.get("headers", []):
        if header == b"x-github-token":
            github_token = value.decode()
            break

    # Store in request context for tools to use
    await transport.handle_request(scope, receive, send)
```

### Client Configuration

**Codex with per-user token:**
```toml
[mcp_servers.github-pr-review]
url = "http://127.0.0.1:8000"
# Option 1: MCP OAuth
bearer_token_env_var = "GITHUB_TOKEN"
# Option 2: Custom header (would need client support)
```

**Claude Code with per-user token:**
```json
{
  "mcpServers": {
    "github-pr-review": {
      "url": "http://127.0.0.1:8000",
      "transport": "http",
      "headers": {
        "X-GitHub-Token": "${GITHUB_TOKEN}"
      }
    }
  }
}
```

## Trade-offs

### Single Server Token (Current)
✅ Simple setup
✅ No client configuration needed
✅ Works immediately
❌ Shared rate limits
❌ All operations use same permissions

### Per-User Tokens
✅ Individual rate limits
✅ User-specific permissions
✅ Better for multi-user deployments
❌ More complex setup
❌ Requires MCP auth implementation
❌ Clients must configure tokens

## Recommendation

**For personal/team use**: Current single-token model is sufficient

**For public/multi-tenant deployments**: Implement per-user token support with:
1. MCP OAuth authentication
2. Token priority: client > server (allow fallback)
3. Clear documentation of rate limit sharing
