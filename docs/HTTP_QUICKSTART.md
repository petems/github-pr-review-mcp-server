# HTTP Mode Quick Start

Get the MCP server running in HTTP mode in 5 minutes.

## Prerequisites

- Python 3.10+
- `uv` package manager
- Docker (optional, for containerized deployment)

## Local Development (5 minutes)

### Step 1: Install Dependencies

```bash
# Clone the repo
git clone https://github.com/cool-kids-inc/github-pr-review-mcp-server.git
cd github-pr-review-mcp-server

# Install with uv
uv sync --dev
```

### Step 2: Set Environment Variables

```bash
# Generate secrets
export MCP_SECRET_KEY=$(openssl rand -base64 32)
export MCP_ADMIN_TOKEN=$(openssl rand -base64 32)
export MCP_MODE=http

# Save for later (optional)
cat > .env.http <<EOF
MCP_MODE=http
MCP_SECRET_KEY=$MCP_SECRET_KEY
MCP_ADMIN_TOKEN=$MCP_ADMIN_TOKEN
RATE_LIMIT_REQUESTS_PER_MINUTE=60
EOF
```

### Step 3: Start the Server

```bash
uv run python -m mcp_github_pr_review.http_server
```

You should see:
```
INFO:     Started server process
INFO:     Uvicorn running on http://0.0.0.0:8080
```

### Step 4: Create a Token

In another terminal:

```bash
# Create token mapping
curl -X POST http://localhost:8080/admin/tokens \
  -H "Authorization: Bearer $MCP_ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "github_token": "ghp_your_github_token_here",
    "user_id": "testuser",
    "description": "Test user token"
  }'
```

Save the `mcp_key` from the response!

### Step 5: Test the API

```bash
# Set your MCP key
export MCP_KEY="mcp_..."  # from step 4

# Fetch PR comments
curl http://localhost:8080/api/fetch-comments \
  -H "Authorization: Bearer $MCP_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "pr_url": "https://github.com/owner/repo/pull/123",
    "output": "json"
  }'
```

## Docker (2 minutes)

### Quick Start

```bash
# Create .env
cat > .env <<EOF
MCP_SECRET_KEY=$(openssl rand -base64 32)
MCP_ADMIN_TOKEN=$(openssl rand -base64 32)
EOF

# Start container
docker-compose up -d

# Check health
curl http://localhost:8080/health
```

### Create Token

```bash
# Load admin token
source .env

# Create token
docker exec mcp-pr-review \
  curl -X POST http://localhost:8080/admin/tokens \
    -H "Authorization: Bearer $MCP_ADMIN_TOKEN" \
    -H "Content-Type: application/json" \
    -d '{"github_token": "ghp_...", "user_id": "user1"}'
```

## GCP Cloud Run (10 minutes)

### Prerequisites

- GCP account with billing enabled
- `gcloud` CLI installed

### Deploy

```bash
# Set project
export PROJECT_ID="your-gcp-project-id"

# Deploy (automated script)
./deploy-cloudrun.sh $PROJECT_ID us-central1
```

The script will:
1. ✅ Enable required APIs
2. ✅ Create secrets automatically
3. ✅ Build and push Docker image
4. ✅ Deploy to Cloud Run
5. ✅ Output service URL

### Get Your Service URL

```bash
gcloud run services describe github-pr-review-mcp \
  --region=us-central1 \
  --format="value(status.url)"
```

### Create Tokens

```bash
SERVICE_URL="https://your-service-abc123.run.app"

# Get admin token
ADMIN_TOKEN=$(gcloud secrets versions access latest --secret=mcp-admin-token)

# Create token
curl -X POST $SERVICE_URL/admin/tokens \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"github_token": "ghp_...", "user_id": "user1"}'
```

## API Endpoints

### Health Check
```bash
GET /health
```

### Root Info
```bash
GET /
# Returns service info and stats
```

### Fetch PR Comments
```bash
POST /api/fetch-comments
Authorization: Bearer <mcp_key>
Content-Type: application/json

{
  "pr_url": "https://github.com/owner/repo/pull/123",
  "output": "markdown",  // or "json" or "both"
  "max_comments": 100
}
```

### SSE Stream (for MCP protocol)
```bash
GET /sse
Authorization: Bearer <mcp_key>
```

### Admin: Create Token
```bash
POST /admin/tokens
Authorization: Bearer <admin_token>
Content-Type: application/json

{
  "github_token": "ghp_...",
  "user_id": "alice",
  "description": "Alice's token"
}
```

### Admin: List Tokens
```bash
GET /admin/tokens
Authorization: Bearer <admin_token>
```

### Admin: Delete Token
```bash
DELETE /admin/tokens/{mcp_key}
Authorization: Bearer <admin_token>
```

## Common Commands

### Check Server Status

```bash
# Health check
curl http://localhost:8080/health

# Detailed info
curl http://localhost:8080/
```

### List All Tokens

```bash
curl http://localhost:8080/admin/tokens \
  -H "Authorization: Bearer $MCP_ADMIN_TOKEN"
```

### Delete a Token

```bash
curl -X DELETE http://localhost:8080/admin/tokens/mcp_abc123... \
  -H "Authorization: Bearer $MCP_ADMIN_TOKEN"
```

### Test Rate Limiting

```bash
# Send multiple requests quickly
for i in {1..70}; do
  curl http://localhost:8080/api/fetch-comments \
    -H "Authorization: Bearer $MCP_KEY" \
    -H "Content-Type: application/json" \
    -d '{"pr_url": "https://github.com/owner/repo/pull/1"}'
done
```

After ~60 requests, you'll see:
```json
{
  "detail": "Rate limit exceeded. Try again in X seconds."
}
```

## Environment Variables Cheat Sheet

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `MCP_MODE` | ✅ | `stdio` | Set to `http` for HTTP mode |
| `MCP_SECRET_KEY` | ✅ (http) | - | Secret key (32+ bytes) |
| `MCP_ADMIN_TOKEN` | ⚠️  | - | Admin API access (recommended) |
| `MCP_HOST` | ❌ | `0.0.0.0` | Bind address |
| `MCP_PORT` | ❌ | `8080` | Server port |
| `RATE_LIMIT_ENABLED` | ❌ | `true` | Enable rate limiting |
| `RATE_LIMIT_REQUESTS_PER_MINUTE` | ❌ | `60` | Max requests per minute |
| `RATE_LIMIT_BURST` | ❌ | `10` | Burst allowance |
| `CORS_ENABLED` | ❌ | `true` | Enable CORS |
| `CORS_ALLOW_ORIGINS` | ❌ | `*` | Allowed origins (comma-separated) |

## Troubleshooting

### Server won't start

**Error**: `MCP_SECRET_KEY is required`
**Fix**: Set `MCP_SECRET_KEY` environment variable

### Can't access admin API

**Error**: `Admin API is not configured`
**Fix**: Set `MCP_ADMIN_TOKEN` environment variable

### Authentication fails

**Error**: `Invalid API key`
**Fix**: Verify token exists with `GET /admin/tokens`

### Rate limit errors

**Error**: `Rate limit exceeded`
**Fix**: Wait for reset (see `Retry-After` header) or increase limits

## Next Steps

- Read the [full deployment guide](HTTP_DEPLOYMENT.md)
- Set up [monitoring and alerts](HTTP_DEPLOYMENT.md#monitoring)
- Configure [CORS for your domain](HTTP_DEPLOYMENT.md#security-best-practices)
- Implement [Redis for persistence](HTTP_DEPLOYMENT.md#redis-migration)

## Getting Help

- **API Documentation**: http://localhost:8080/docs (when running)
- **Full Guide**: [HTTP_DEPLOYMENT.md](HTTP_DEPLOYMENT.md)
- **Issues**: https://github.com/cool-kids-inc/github-pr-review-mcp-server/issues
