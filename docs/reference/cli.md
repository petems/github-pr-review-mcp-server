# CLI Reference

The package installs the console script `mcp-github-pr-review`. The CLI accepts the following options:

```text
Usage: mcp-github-pr-review [OPTIONS]

Run the GitHub PR Review MCP server over stdio.

Options:
  --env-file ENV_FILE       Optional path to a .env file to load before starting the server.
  --max-pages MAX_PAGES     Override PR_FETCH_MAX_PAGES for this process.
  --max-comments MAX_COMMENTS
                           Override PR_FETCH_MAX_COMMENTS for this process.
  --per-page PER_PAGE      Override HTTP_PER_PAGE for this process.
  --max-retries MAX_RETRIES
                           Override HTTP_MAX_RETRIES for this process.
  -h, --help               Show this help message and exit.
```

## Options

| Option | Type | Description |
| --- | --- | --- |
| `--env-file PATH` | string | Load environment variables from a custom `.env` file path. |
| `--max-pages N` | integer | Override `PR_FETCH_MAX_PAGES` for this process (default: 50). Must be positive. |
| `--max-comments N` | integer | Override `PR_FETCH_MAX_COMMENTS` for this process (default: 2000). Must be positive. |
| `--per-page N` | integer | Override `HTTP_PER_PAGE` for this process (default: 100, max: 100). Must be positive. |
| `--max-retries N` | integer | Override `HTTP_MAX_RETRIES` for this process (default: 3). Must be positive. |
| `-h, --help` | - | Show usage information and exit. |

## Examples

```bash
# Run with default settings
mcp-github-pr-review

# Load custom environment file
mcp-github-pr-review --env-file /path/to/.env

# Override pagination limits
mcp-github-pr-review --max-pages 20 --max-comments 500

# Adjust API behavior
mcp-github-pr-review --per-page 50 --max-retries 5
```

## Environment Variables

Command-line flags take precedence over environment variables. Environment variables can be set in:
- Shell environment
- `.env` file in the current directory (auto-loaded)
- Custom `.env` file via `--env-file`

See [Environment Reference](environment.md) for the complete list of supported environment variables.
