# MCP HTTP Streaming Testing Guide

This guide explains how to test and configure the HTTP streaming mode for the GitHub PR Review MCP server.

## ⚠️ Important: Required Headers

**All HTTP requests must include BOTH accept types (MCP protocol requirement):**

```http
Content-Type: application/json
Accept: application/json, text/event-stream
```

**Note:** Even though this server only returns JSON responses, the MCP protocol validates that clients accept both types for protocol compatibility. This is NOT because we use any event streaming - it's purely HTTP streaming with JSON.

## Prerequisites

1. Set your GitHub token:
   ```bash
   export GITHUB_TOKEN="your_github_token_here"
   ```

2. Install the server:
   ```bash
   uv sync
   ```

## Testing the HTTP Server

### Option 1: Automated Test Script

Run the included test script:

```bash
# Terminal 1: Start the server
uv run mcp-github-pr-review http

# Terminal 2: Run the test script
uv run python test_http_mcp.py
```

The test script validates:
- ✅ Server initialization
- ✅ Tool listing
- ✅ Tool invocation (resolve_open_pr_url)

### Option 2: Manual curl Tests

```bash
# 1. Initialize connection
curl -X POST http://127.0.0.1:8000 \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
      "protocolVersion": "2024-11-05",
      "capabilities": {},
      "clientInfo": {
        "name": "test-client",
        "version": "1.0.0"
      }
    }
  }' | jq .

# 2. List tools
curl -X POST http://127.0.0.1:8000 \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{
    "jsonrpc": "2.0",
    "id": 2,
    "method": "tools/list"
  }' | jq .

# 3. Call a tool
curl -X POST http://127.0.0.1:8000 \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{
    "jsonrpc": "2.0",
    "id": 3,
    "method": "tools/call",
    "params": {
      "name": "resolve_open_pr_url",
      "arguments": {
        "owner": "cool-kids-inc",
        "repo": "github-pr-review-mcp-server",
        "branch": "main",
        "select_strategy": "latest"
      }
    }
  }' | jq .
```

### Option 3: Interactive Python Test

```python
import httpx
import json

# Start interactive session
async def test():
    async with httpx.AsyncClient() as client:
        # Initialize
        resp = await client.post(
            "http://127.0.0.1:8000",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "test", "version": "1.0"}
                }
            },
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream"
            }
        )
        print(json.dumps(resp.json(), indent=2))

# Run it
import asyncio
asyncio.run(test())
```

## Client Configuration

### Claude Code (Desktop App)

For local development (recommended):

```json
{
  "mcpServers": {
    "github-pr-review": {
      "command": "uv",
      "args": [
        "--directory",
        "/Users/peter.souter/projects/github-pr-review-mcp-server",
        "run",
        "mcp-github-pr-review",
        "stdio"
      ],
      "env": {
        "GITHUB_TOKEN": "your-token-here"
      }
    }
  }
}
```

For remote HTTP server:

```json
{
  "mcpServers": {
    "github-pr-review-http": {
      "url": "http://127.0.0.1:8000",
      "transport": "http"
    }
  }
}
```

### Cursor / Windsurf (VS Code-based)

**Stdio mode (recommended for local):**
```json
{
  "mcpServers": {
    "github-pr-review": {
      "command": "uv",
      "args": [
        "--directory",
        "/absolute/path/to/github-pr-review-mcp-server",
        "run",
        "mcp-github-pr-review",
        "stdio"
      ],
      "env": {
        "GITHUB_TOKEN": "ghp_your_token_here"
      }
    }
  }
}
```

**HTTP mode (for remote servers):**
```json
{
  "mcpServers": {
    "github-pr-review-http": {
      "url": "http://your-server:8000",
      "transport": "http",
      "env": {
        "GITHUB_TOKEN": "ghp_your_token_here"
      }
    }
  }
}
```

### Cline (VS Code Extension)

Add to VS Code settings (`.vscode/settings.json`):

```json
{
  "cline.mcpServers": {
    "github-pr-review": {
      "command": "uv",
      "args": [
        "--directory",
        "/absolute/path/to/github-pr-review-mcp-server",
        "run",
        "mcp-github-pr-review",
        "stdio"
      ],
      "env": {
        "GITHUB_TOKEN": "ghp_your_token_here"
      }
    }
  }
}
```

### Generic MCP Client (HTTP)

```javascript
// Example with @modelcontextprotocol/sdk
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { HttpClientTransport } from "@modelcontextprotocol/sdk/client/http.js";

const transport = new HttpClientTransport(
  new URL("http://127.0.0.1:8000")
);

const client = new Client(
  {
    name: "my-client",
    version: "1.0.0",
  },
  {
    capabilities: {},
  }
);

await client.connect(transport);

// List tools
const tools = await client.listTools();
console.log(tools);

// Call tool
const result = await client.callTool({
  name: "resolve_open_pr_url",
  arguments: {
    owner: "cool-kids-inc",
    repo: "github-pr-review-mcp-server",
    branch: "main"
  }
});
```

## Production Deployment

### Docker Compose

```yaml
version: '3.8'

services:
  mcp-server:
    build: .
    ports:
      - "8000:8000"
    environment:
      - GITHUB_TOKEN=${GITHUB_TOKEN}
    command: ["uv", "run", "mcp-github-pr-review", "http", "--host", "0.0.0.0"]
```

### Environment Variables

Both stdio and http modes support the same configuration:

```bash
export GITHUB_TOKEN="ghp_your_token"
export GH_HOST="github.com"  # or enterprise hostname
export PR_FETCH_MAX_PAGES="50"
export PR_FETCH_MAX_COMMENTS="2000"
export HTTP_PER_PAGE="100"
export HTTP_MAX_RETRIES="3"
```

## Debugging

### Enable verbose logging

```bash
# Start server with debug output
uv run mcp-github-pr-review http --host 127.0.0.1 --port 8000

# Watch requests in real-time
tail -f /dev/stderr  # Server logs to stderr
```

### Check server health

```bash
# Server should respond to any MCP method
curl -X POST http://127.0.0.1:8000 \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'

# Check if it's actually running
lsof -i :8000
```

## When to Use HTTP vs Stdio

**Use Stdio when:**
- ✅ Running locally with Claude Code CLI
- ✅ Single-user development environment
- ✅ Want simplest configuration
- ✅ Don't need network access

**Use HTTP when:**
- ✅ Deploying to remote server/cloud
- ✅ Multiple clients connecting
- ✅ Web-based MCP clients
- ✅ Docker/container deployments
- ✅ Need to access from different machines
- ✅ Integration with web APIs

## Troubleshooting

### Server won't start
```bash
# Check if port is already in use
lsof -i :8000

# Try different port
uv run mcp-github-pr-review http --port 8001
```

### Connection refused
```bash
# Make sure server is running
ps aux | grep mcp-github-pr-review

# Check firewall settings
# Make sure 127.0.0.1:8000 is accessible
```

### Authentication errors
```bash
# Verify token is set
echo $GITHUB_TOKEN

# Test token with GitHub API
curl -H "Authorization: Bearer $GITHUB_TOKEN" https://api.github.com/user
```

## Next Steps

1. Run the automated test: `uv run python test_http_mcp.py`
2. Try manual curl commands to understand the protocol
3. Configure your preferred MCP client
4. For local development, use stdio mode for simplicity
5. For production/remote access, use http mode with proper security
