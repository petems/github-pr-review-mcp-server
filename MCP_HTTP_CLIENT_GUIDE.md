# MCP HTTP Client Configuration Guide

## Header Requirements

**The MCP protocol requires BOTH accept types:**

```http
Content-Type: application/json
Accept: application/json, text/event-stream
```

**Important:** Even though this server only returns JSON responses (no event streaming), the MCP protocol validates that clients declare support for both content types. This is a protocol-level requirement for compatibility, not because we use event streams.

## Client Compatibility

### ✅ Automatically Compatible

These clients work with standard HTTP headers:

1. **Official MCP SDK** (`@modelcontextprotocol/sdk`)
2. **Claude Desktop** - When configured for HTTP transport
3. **Cline** - When using HTTP mode
4. **Cursor/Windsurf** - When using HTTP transport

### Configuration Examples

#### curl

```bash
curl -X POST http://127.0.0.1:8000 \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
```

#### httpx (Python)

```python
headers = {
    "Content-Type": "application/json",
    "Accept": "application/json, text/event-stream"
}
response = await client.post(url, json=data, headers=headers)
```

#### requests (Python)

```python
headers = {
    "Content-Type": "application/json",
    "Accept": "application/json, text/event-stream"
}
response = requests.post(url, json=data, headers=headers)
```

#### fetch (JavaScript)

```javascript
fetch('http://127.0.0.1:8000', {
  method: 'POST',
  headers: {
    'Content-Type': 'application/json',
    'Accept': 'application/json'
  },
  body: JSON.stringify(request)
})
```

## Testing Header Configuration

```bash
# Test with correct headers
curl -X POST http://127.0.0.1:8000 \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' | jq .
```

## Client Configuration Examples

### Claude Desktop

Edit `~/.config/claude-code/config.json`:

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

### Generic HTTP Client Library

```python
import httpx
import json

class MCPHTTPClient:
    def __init__(self, base_url: str):
        self.base_url = base_url
        self.headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream"
        }

    async def call_tool(self, name: str, arguments: dict):
        async with httpx.AsyncClient() as client:
            response = await client.post(
                self.base_url,
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/call",
                    "params": {
                        "name": name,
                        "arguments": arguments
                    }
                },
                headers=self.headers
            )
            return response.json()

# Usage
client = MCPHTTPClient("http://127.0.0.1:8000")
result = await client.call_tool("resolve_open_pr_url", {
    "owner": "cool-kids-inc",
    "repo": "github-pr-review-mcp-server",
    "branch": "main"
})
```

### Node.js MCP Client

```javascript
const { Client } = require("@modelcontextprotocol/sdk/client/index.js");
const { HttpClientTransport } = require("@modelcontextprotocol/sdk/client/http.js");

// Create transport
const transport = new HttpClientTransport(
  new URL("http://127.0.0.1:8000")
);

// Create client
const client = new Client(
  {
    name: "my-app",
    version: "1.0.0",
  },
  {
    capabilities: {},
  }
);

// Connect
await client.connect(transport);

// Use tools
const tools = await client.listTools();
const result = await client.callTool({
  name: "resolve_open_pr_url",
  arguments: {
    owner: "cool-kids-inc",
    repo: "github-pr-review-mcp-server",
    branch: "main"
  }
});
```

## Troubleshooting

### Connection Refused

**Problem:** Server not running or wrong port

**Solution:**
```bash
# Check if server is running
lsof -i :8000

# Start server
uv run mcp-github-pr-review http
```

### CORS Issues (Browser Clients)

If accessing from browser, you may need CORS headers. The current implementation doesn't add CORS headers by default.

## Recommendations

### For Production Use

1. **Use official MCP SDK clients** - They handle protocol correctly
2. **For AI coding assistants** - Use stdio mode locally, HTTP mode for remote
3. **For custom HTTP clients** - Use standard JSON headers
4. **Document requirements** - Include in your API documentation

### For Development/Testing

Use the provided `test_http_mcp.py` script:

```bash
uv run python test_http_mcp.py
```

## Summary

✅ **Standard HTTP/JSON**
- Uses JSON-RPC 2.0 protocol
- Standard Content-Type and Accept headers
- Works with any HTTP client
- No special streaming protocols required
