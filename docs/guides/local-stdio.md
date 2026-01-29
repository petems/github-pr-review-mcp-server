# Local stdio Execution

The fastest way to run the server is locally over stdio, which is the default transport for most MCP hosts.

## Setup Checklist

1. Install the package (`uv tool install mcp-github-pr-review` or `uv add mcp-github-pr-review`).
2. Export `GITHUB_TOKEN` in your shell or write it to `.env`.
3. Launch the entry point:
   ```bash
   mcp-github-pr-review
   ```
4. Register the server with your host using the configuration commands below.

## Optional Flags

| Flag | Description |
| --- | --- |
| `--env-file PATH` | Load environment variables from a custom .env file. |
| `--max-comments N` | Override `PR_FETCH_MAX_COMMENTS` for the process lifetime. |
| `--max-pages N` | Override `PR_FETCH_MAX_PAGES`. |
| `--per-page N` | Override `HTTP_PER_PAGE` (GitHub API page size, 1-100). |
| `--max-retries N` | Override `HTTP_MAX_RETRIES` (retry limit for transient errors). |

## Host Configuration Examples

Below are configuration examples for popular MCP hosts. All examples assume:
- You've installed the package (`uv add mcp-github-pr-review` or globally via `uvx`)
- Your `GITHUB_TOKEN` is exported in your shell or available in `.env`

### CLI-Based Configuration (Recommended)

Several MCP hosts support adding servers via command-line interface, which is often faster and less error-prone than manual JSON editing.

#### Claude Code CLI

Add the server using the `claude mcp add` command:

```bash
# Basic setup (inherits GITHUB_TOKEN from shell environment)
claude mcp add github-pr-review --scope user --transport stdio --env GITHUB_TOKEN="${GITHUB_TOKEN}" -- mcp-github-pr-review

# With explicit environment variable (not recommended - use shell env instead)
claude mcp add github-pr-review --scope user --transport stdio --env GITHUB_TOKEN=your_token_here -- mcp-github-pr-review

# With additional flags for pagination limits
claude mcp add github-pr-review --scope user --transport stdio --env GITHUB_TOKEN="${GITHUB_TOKEN}" -- mcp-github-pr-review --max-comments 500 --max-pages 20

# Using uvx (if not installed as a tool)
claude mcp add github-pr-review --scope user --transport stdio --env GITHUB_TOKEN="${GITHUB_TOKEN}" -- uvx mcp-github-pr-review

# Using short flags
claude mcp add github-pr-review -s user -t stdio -e GITHUB_TOKEN="${GITHUB_TOKEN}" -- mcp-github-pr-review
```

**Key points:**
- Format: `claude mcp add SERVER_NAME [OPTIONS] -- COMMAND [ARGS]`
- The server name comes FIRST, before any options
- All options (`--scope`, `--transport`, `--env`) come after the server name but before `--`
- The `--` separator divides configuration from the command to execute
- Use `--scope user` (or `-s user`) for global availability (recommended)
- Use `--transport stdio` (or `-t stdio`) to specify stdio transport (default)
- Supported MCP server flags: `--max-comments`, `--max-pages`, `--per-page`, `--max-retries`, `--env-file`
- The `--log-level` flag is NOT supported (it was shown in error in previous versions)

#### VS Code CLI (Native MCP)

Add the server using the `code` command:

```bash
# Basic setup with uvx
code --add-mcp '{"name":"github-pr-review","command":"uvx","args":["mcp-github-pr-review"]}'

# With environment variable
code --add-mcp '{"name":"github-pr-review","command":"uvx","args":["mcp-github-pr-review"],"env":{"GITHUB_TOKEN":"your_token_here"}}'

# With pagination limits
code --add-mcp '{"name":"github-pr-review","command":"uvx","args":["mcp-github-pr-review","--max-comments","500","--max-pages","20"]}'
```

**Note:** Requires VS Code 1.102+ with native MCP support. The JSON must be properly escaped in the shell.

#### Cursor CLI (Interactive)

Use Cursor's interactive MCP commands:

```bash
# Open interactive MCP menu to browse and configure servers
cursor /mcp list

# Enable a configured MCP server
cursor /mcp enable github-pr-review

# Disable an MCP server
cursor /mcp disable github-pr-review
```

**Note:** These commands require Cursor CLI (January 2026+). For initial setup, you'll still need to create the JSON configuration first, then use these commands to manage it.

### Manual JSON Configuration

For hosts without CLI support, or if you prefer manual configuration:

#### Claude Desktop (Claude Code)

**Note:** Prefer using `claude mcp add` CLI command (see above). For manual configuration, edit:
- macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`
- Windows: `%APPDATA%\Claude\claude_desktop_config.json`

```json
{
  "mcpServers": {
    "github-pr-review": {
      "command": "uvx",
      "args": ["mcp-github-pr-review"],
      "env": {
        "GITHUB_TOKEN": "your_github_token_here"
      }
    }
  }
}
```

**Alternative with installed package:**
```json
{
  "mcpServers": {
    "github-pr-review": {
      "command": "mcp-github-pr-review",
      "args": ["--max-comments", "500", "--max-pages", "20"]
    }
  }
}
```

#### Cursor IDE

**Note:** Use `cursor /mcp list` CLI command for interactive management (see CLI section above). For manual configuration, create:
- Project-level: `.cursor/mcp.json` in your project directory
- Global: `~/.cursor/mcp.json` in your home directory

```json
{
  "mcpServers": {
    "github-pr-review": {
      "command": "uvx",
      "args": ["mcp-github-pr-review"],
      "env": {
        "GITHUB_TOKEN": "your_github_token_here"
      }
    }
  }
}
```

After creating the file, use `cursor /mcp enable github-pr-review` to activate it. Cursor also supports one-click setup for curated MCP servers.

#### Cline (VS Code Extension)

**Manual configuration:**
1. Click the "MCP Servers" icon in Cline's top navigation bar
2. Select the "Configure" tab
3. Click "Configure MCP Servers" button
4. Add to `cline_mcp_settings.json`:

```json
{
  "mcpServers": {
    "github-pr-review": {
      "command": "uvx",
      "args": ["mcp-github-pr-review"],
      "env": {
        "GITHUB_TOKEN": "your_github_token_here"
      }
    }
  }
}
```

**Note:** Cline supports `${workspaceFolder}` variable for dynamic workspace paths if needed for log files.

#### Continue.dev (VS Code Extension)

**Manual configuration:** Create directory `.continue/mcpServers/` at your workspace root and add `github-pr-review.json`:

```json
{
  "name": "github-pr-review",
  "command": "uvx",
  "args": ["mcp-github-pr-review"],
  "env": {
    "GITHUB_TOKEN": "your_github_token_here"
  }
}
```

**Alternative YAML format** (create `github-pr-review.yaml`):
```yaml
name: github-pr-review
command: uvx
args:
  - mcp-github-pr-review
env:
  GITHUB_TOKEN: your_github_token_here
```

**Note:** Continue.dev only supports MCP in agent mode. Files in `.continue/mcpServers/` are automatically picked up.

#### VS Code Native (GitHub Copilot)

**Note:** VS Code 1.102+ supports MCP natively. Use `code --add-mcp` CLI command (see CLI section above) or manually create `.vscode/mcp.json`:

```json
{
  "mcpServers": {
    "github-pr-review": {
      "command": "uvx",
      "args": ["mcp-github-pr-review"],
      "env": {
        "GITHUB_TOKEN": "your_github_token_here"
      }
    }
  }
}
```

You can also use VS Code Command Palette: type `@mcp` in Extensions view or run "MCP: Browse Servers" / "MCP: List Servers" commands.

### Security Best Practices

**Never commit tokens directly in configuration files.** Use one of these approaches:

1. **Environment variable reference** (if supported by your host):
   ```json
   "env": {
     "GITHUB_TOKEN": "${GITHUB_TOKEN}"
   }
   ```

2. **Keep token in shell environment only** and omit the `env` block entirely (works if the command inherits your shell environment)

3. **Use `.env` file** in your project root (server will automatically load it)

## Troubleshooting

- **401 Unauthorized**: Validate token scopes and ensure you are not mixing fine-grained and classic tokens.
- **Timeouts**: Increase `HTTP_MAX_RETRIES` and review network firewall policies.
- **Input Path Errors**: Upgrade to the latest version to pick up improvements in Dulwich-based repository detection.
- **Server not appearing**: Restart your MCP host after adding configuration. For Claude Desktop, quit and reopen the application.
- **Permission errors**: Ensure `uvx` or `mcp-github-pr-review` is in your PATH and executable.
