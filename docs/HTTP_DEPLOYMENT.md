# HTTP/SSE Deployment Guide

This guide covers deploying the GitHub PR Review MCP Server in HTTP mode with SSE transport for remote access.

## Table of Contents

- [Overview](#overview)
- [Quick Start](#quick-start)
- [Architecture](#architecture)
- [Deployment Options](#deployment-options)
- [Configuration](#configuration)
- [Token Management](#token-management)
- [Security Best Practices](#security-best-practices)
- [Monitoring](#monitoring)
- [Troubleshooting](#troubleshooting)

## Overview

The HTTP mode allows the MCP server to be deployed remotely and accessed over HTTPS using Server-Sent Events (SSE) for real-time communication. This enables:

- **Multi-user access**: Multiple clients can connect simultaneously
- **Remote deployment**: Deploy to cloud platforms (GCP, AWS, Azure)
- **Per-user authentication**: Each user has their own API key and GitHub token
- **Rate limiting**: Protect against abuse with configurable limits
- **Centralized management**: Admin API for token management

## Quick Start

### Local Development

1. **Install dependencies**:
   ```bash
   uv sync --dev
   ```

2. **Set environment variables**:
   ```bash
   export MCP_MODE=http
   export MCP_SECRET_KEY=$(openssl rand -base64 32)
   export MCP_ADMIN_TOKEN=$(openssl rand -base64 32)
   ```

3. **Run the server**:
   ```bash
   uv run python -m mcp_github_pr_review.http_server
   ```

4. **Create a token mapping**:
   ```bash
   curl -X POST http://localhost:8080/admin/tokens \
     -H "Authorization: Bearer $MCP_ADMIN_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{"github_token": "ghp_your_token", "user_id": "user1"}'
   ```

5. **Test the API**:
   ```bash
   MCP_KEY="<key-from-step-4>"
   curl http://localhost:8080/api/fetch-comments \
     -H "Authorization: Bearer $MCP_KEY" \
     -H "Content-Type: application/json" \
     -d '{"pr_url": "https://github.com/owner/repo/pull/123"}'
   ```

### Docker Compose

1. **Create `.env` file**:
   ```bash
   cat > .env <<EOF
   MCP_SECRET_KEY=$(openssl rand -base64 32)
   MCP_ADMIN_TOKEN=$(openssl rand -base64 32)
   EOF
   ```

2. **Start services**:
   ```bash
   docker-compose up -d
   ```

3. **Check health**:
   ```bash
   curl http://localhost:8080/health
   ```

## Architecture

### Approach B-Lite (In-Memory)

The current implementation uses **Approach B-Lite** from the architectural review:

- **Transport**: FastAPI + sse-starlette for HTTP/SSE
- **Auth**: API key validation (Bearer tokens)
- **Token Storage**: In-memory mapping (MCP API key → GitHub token)
- **Rate Limiting**: In-memory sliding window algorithm
- **State**: Stateless (tokens lost on restart)

**Upgrading to Redis**: The interfaces are designed to support Redis. See [Redis Migration Guide](#redis-migration) below.

### Request Flow

```
┌─────────┐      ┌──────────────┐      ┌────────────┐      ┌────────────┐
│ Client  │─────▶│ FastAPI      │─────▶│ Auth       │─────▶│ Token      │
│         │      │ HTTP Server  │      │ Middleware │      │ Store      │
└─────────┘      └──────────────┘      └────────────┘      └────────────┘
                        │                      │                    │
                        │                      ▼                    │
                        │              ┌────────────┐               │
                        │              │ Rate       │               │
                        │              │ Limiter    │               │
                        │              └────────────┘               │
                        │                                           │
                        ▼                                           ▼
                 ┌──────────────┐                          ┌─────────────┐
                 │ MCP Server   │─────────────────────────▶│ GitHub API  │
                 │ Logic        │                          │             │
                 └──────────────┘                          └─────────────┘
```

## Deployment Options

### GCP Cloud Run (Recommended)

**Pros**: Auto-scaling, pay-per-use, managed infrastructure, HTTPS included
**Cost**: ~$20-35/month for moderate use

```bash
# Set your project
export PROJECT_ID="your-gcp-project"

# Deploy
./deploy-cloudrun.sh $PROJECT_ID us-central1
```

The script will:
1. Enable required APIs
2. Create secrets (MCP_SECRET_KEY, MCP_ADMIN_TOKEN)
3. Build and push Docker image
4. Deploy to Cloud Run
5. Output the service URL

### Render.com

**Pros**: Simple setup, free tier, auto-deploy from Git
**Cost**: $0 (free tier) or $7/month (starter)

1. **Create `render.yaml`** (in project root):
   ```yaml
   services:
     - type: web
       name: mcp-pr-review
       env: docker
       plan: free
       envVars:
         - key: MCP_MODE
           value: http
         - key: MCP_SECRET_KEY
           generateValue: true
         - key: MCP_ADMIN_TOKEN
           generateValue: true
         - key: RATE_LIMIT_ENABLED
           value: true
         - key: CORS_ALLOW_ORIGINS
           value: "*"
       healthCheckPath: /health
   ```

2. **Deploy**:
   - Connect your GitHub repo to Render
   - Select "New Web Service"
   - Choose "Docker" environment
   - Render will auto-deploy on git push

### Hugging Face Spaces

**Pros**: Free hosting, GPU available, ML-friendly community
**Cost**: $0 (free tier)

1. **Create `Dockerfile.hf`** (port 7860 required):
   ```dockerfile
   FROM python:3.11-slim
   # ... (similar to Dockerfile but use port 7860)
   ENV PORT=7860
   EXPOSE 7860
   ```

2. **Push to Hugging Face**:
   ```bash
   git remote add hf https://huggingface.co/spaces/your-username/mcp-pr-review
   git push hf main
   ```

## Configuration

### Environment Variables

**Required (stdio mode)**:
- `GITHUB_TOKEN`: GitHub PAT (not needed in http mode if using per-user tokens)

**Required (http mode)**:
- `MCP_SECRET_KEY`: Secret key for operations (32+ bytes)
- `MCP_MODE=http`: Enable HTTP server mode

**Optional**:
- `MCP_HOST`: Bind address (default: `0.0.0.0`)
- `MCP_PORT`: Server port (default: `8080`)
- `MCP_ADMIN_TOKEN`: Admin API key (required for `/admin/*` endpoints)
- `RATE_LIMIT_ENABLED`: Enable rate limiting (default: `true`)
- `RATE_LIMIT_REQUESTS_PER_MINUTE`: Max requests per minute (default: `60`)
- `RATE_LIMIT_BURST`: Burst allowance (default: `10`)
- `CORS_ENABLED`: Enable CORS (default: `true`)
- `CORS_ALLOW_ORIGINS`: Comma-separated origins (default: `*`)

### Configuration File

Create `.env` file:

```bash
# Server Mode
MCP_MODE=http
MCP_HOST=0.0.0.0
MCP_PORT=8080

# Authentication
MCP_SECRET_KEY=<generated-secret>
MCP_ADMIN_TOKEN=<admin-token>

# Rate Limiting
RATE_LIMIT_ENABLED=true
RATE_LIMIT_REQUESTS_PER_MINUTE=60
RATE_LIMIT_BURST=10

# CORS
CORS_ENABLED=true
CORS_ALLOW_ORIGINS=https://yourapp.com,https://claude.ai
CORS_ALLOW_CREDENTIALS=true
```

## Token Management

### Creating Tokens

Use the admin API to create MCP API keys and map them to GitHub tokens:

```bash
# Create a token mapping
curl -X POST https://your-server.com/admin/tokens \
  -H "Authorization: Bearer $MCP_ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "github_token": "ghp_your_github_token",
    "user_id": "alice",
    "description": "Alice's token for PR reviews"
  }'

# Response
{
  "mcp_key": "mcp_abc123...",
  "user_id": "alice",
  "description": "Alice's token for PR reviews",
  "created_at": "2026-01-28T10:00:00Z"
}
```

### Listing Tokens

```bash
curl https://your-server.com/admin/tokens \
  -H "Authorization: Bearer $MCP_ADMIN_TOKEN"
```

### Deleting Tokens

```bash
curl -X DELETE https://your-server.com/admin/tokens/mcp_abc123... \
  -H "Authorization: Bearer $MCP_ADMIN_TOKEN"
```

### Token Distribution

**Give users their MCP API key** (starts with `mcp_`), which they'll use in the `Authorization: Bearer <token>` header.

**Security note**: Users never see your `MCP_ADMIN_TOKEN` or each other's GitHub tokens.

## Security Best Practices

### 1. Use Secrets Management

**GCP Secret Manager**:
```bash
# Store secret
echo -n "your-secret" | gcloud secrets create mcp-secret-key --data-file=-

# Grant Cloud Run access
gcloud secrets add-iam-policy-binding mcp-secret-key \
  --member="serviceAccount:PROJECT_ID-compute@developer.gserviceaccount.com" \
  --role="roles/secretmanager.secretAccessor"
```

**Docker Secrets**:
```bash
docker secret create mcp_secret_key ./secret.txt
```

### 2. Restrict CORS Origins

In production, limit CORS to trusted origins:

```bash
CORS_ALLOW_ORIGINS=https://yourapp.com,https://app.example.com
```

### 3. Use HTTPS

All production deployments should use HTTPS. Cloud platforms provide this by default.

### 4. Rotate Secrets

Regularly rotate `MCP_SECRET_KEY` and `MCP_ADMIN_TOKEN`:

```bash
# Generate new keys
export NEW_SECRET=$(openssl rand -base64 32)
export NEW_ADMIN=$(openssl rand -base64 32)

# Update in your deployment
gcloud secrets versions add mcp-secret-key --data-file=- <<< "$NEW_SECRET"
```

### 5. Monitor Access

Enable logging and monitoring:

```bash
# GCP: View logs
gcloud run services logs tail github-pr-review-mcp --region=us-central1

# Look for authentication failures
gcloud logging read "resource.type=cloud_run_revision AND textPayload=~'Authentication failed'"
```

### 6. Rate Limit Configuration

Tune rate limits based on usage:

```bash
# Conservative (for public APIs)
RATE_LIMIT_REQUESTS_PER_MINUTE=30
RATE_LIMIT_BURST=5

# Generous (for internal tools)
RATE_LIMIT_REQUESTS_PER_MINUTE=120
RATE_LIMIT_BURST=20
```

## Monitoring

### Health Checks

```bash
# Basic health check
curl https://your-server.com/health

# Detailed stats
curl https://your-server.com/
```

### Metrics to Monitor

1. **Request rate**: Requests per minute
2. **Error rate**: 4xx/5xx responses
3. **Latency**: p50, p95, p99 response times
4. **Active tokens**: Number of registered users
5. **Rate limit hits**: How often users hit limits

### GCP Monitoring

```bash
# Set up alerting
gcloud alpha monitoring policies create \
  --notification-channels=CHANNEL_ID \
  --display-name="MCP Server Errors" \
  --condition-display-name="High Error Rate" \
  --condition-expression='
    resource.type="cloud_run_revision" AND
    metric.type="run.googleapis.com/request_count" AND
    metric.labels.response_code_class="5xx"
  '
```

## Troubleshooting

### Common Issues

#### 1. "Missing Authorization header"

**Cause**: No Bearer token provided
**Fix**: Include header: `Authorization: Bearer mcp_your_key`

#### 2. "Invalid API key"

**Cause**: Token not registered or expired
**Fix**: Create token via admin API or check token mapping

#### 3. "Rate limit exceeded"

**Cause**: Too many requests
**Fix**: Wait for reset time (see `Retry-After` header) or request limit increase

#### 4. "GitHub token configuration error"

**Cause**: Token mapping exists but GitHub token is invalid/missing
**Fix**: Update token mapping with valid GitHub PAT

#### 5. "CORS error in browser"

**Cause**: CORS not configured for your origin
**Fix**: Add origin to `CORS_ALLOW_ORIGINS` environment variable

### Debug Mode

Enable debug logging:

```bash
export LOG_LEVEL=DEBUG
python -m mcp_github_pr_review.http_server
```

### Testing with curl

```bash
# Test authentication
curl -v https://your-server.com/api/fetch-comments \
  -H "Authorization: Bearer $MCP_KEY" \
  -H "Content-Type: application/json" \
  -d '{"pr_url": "https://github.com/owner/repo/pull/1"}'

# Check headers
curl -I https://your-server.com/health
```

## Redis Migration

To upgrade from in-memory to Redis:

1. **Add Redis dependency**:
   ```bash
   uv add redis
   ```

2. **Create Redis token store** (`redis_token_store.py`):
   ```python
   import redis.asyncio as aioredis
   from .token_store import TokenStore

   class RedisTokenStore(TokenStore):
       def __init__(self, redis_url: str):
           self.redis = aioredis.from_url(redis_url)
       # Implement TokenStore protocol
   ```

3. **Update configuration**:
   ```bash
   export REDIS_URL=redis://localhost:6379
   export TOKEN_STORAGE=redis
   ```

4. **Update server initialization**:
   ```python
   if settings.token_storage == "redis":
       store = RedisTokenStore(settings.redis_url)
   else:
       store = InMemoryTokenStore()
   ```

## Next Steps

- Set up CI/CD for automatic deployments
- Implement token expiration and rotation
- Add request logging and analytics
- Set up monitoring dashboards
- Configure backup and disaster recovery

## Support

For issues or questions:
- GitHub Issues: https://github.com/cool-kids-inc/github-pr-review-mcp-server/issues
- Documentation: https://cool-kids-inc.github.io/github-pr-review-mcp-server/
