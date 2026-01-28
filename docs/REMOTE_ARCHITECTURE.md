# Remote MCP Server Architecture

This document describes the architecture of the HTTP/SSE deployment mode for the GitHub PR Review MCP Server.

## Overview

The MCP server supports two deployment modes:

1. **stdio mode** (original): Local deployment, communicates via stdin/stdout
2. **http mode** (new): Remote deployment, communicates via HTTP/SSE

This document focuses on the **http mode** architecture.

## High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                         Client Applications                          │
│  (Claude Desktop, VS Code, Browser, CLI tools)                      │
└────────────────┬────────────────────────────────────────────────────┘
                 │ HTTPS + Bearer Token
                 │
                 ▼
┌─────────────────────────────────────────────────────────────────────┐
│                     Load Balancer / CDN                              │
│                (GCP Cloud Run, Render, etc.)                         │
└────────────────┬────────────────────────────────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────────────────────────────────┐
│                      FastAPI HTTP Server                             │
│                                                                       │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐              │
│  │ CORS         │→ │ Auth         │→ │ Rate         │              │
│  │ Middleware   │  │ Middleware   │  │ Limiter      │              │
│  └──────────────┘  └──────────────┘  └──────────────┘              │
│                                                                       │
│  ┌───────────────────────────────────────────────────────────┐     │
│  │                    API Endpoints                           │     │
│  │  • POST /api/fetch-comments                               │     │
│  │  • GET  /sse  (SSE stream)                                │     │
│  │  • POST /admin/tokens                                     │     │
│  │  • GET  /admin/tokens                                     │     │
│  │  • DELETE /admin/tokens/{key}                             │     │
│  └───────────────────────────────────────────────────────────┘     │
└────────────────┬────────────────────────────────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────────────────────────────────┐
│                     In-Memory State                                  │
│                                                                       │
│  ┌──────────────┐              ┌──────────────┐                    │
│  │ Token Store  │              │ Rate Limiter │                    │
│  │              │              │              │                    │
│  │ mcp_key_123  │              │ User: Alice  │                    │
│  │  ↓           │              │  Requests: 45│                    │
│  │ ghp_xyz...   │              │  Window: 60s │                    │
│  └──────────────┘              └──────────────┘                    │
└─────────────────────────────────────────────────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────────────────────────────────┐
│                      MCP Server Logic                                │
│              (Existing PR comment fetching logic)                    │
└────────────────┬────────────────────────────────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────────────────────────────────┐
│                       GitHub API                                     │
│              (REST + GraphQL endpoints)                              │
└─────────────────────────────────────────────────────────────────────┘
```

## Component Details

### 1. FastAPI HTTP Server (`http_server.py`)

**Responsibilities**:
- HTTP request routing
- OpenAPI documentation generation
- CORS configuration
- Lifecycle management (startup/shutdown)

**Key Endpoints**:
- `GET /health`: Health check
- `GET /`: Service information
- `POST /api/fetch-comments`: Fetch PR comments (authenticated)
- `GET /sse`: SSE stream for MCP protocol (authenticated)
- `POST /admin/tokens`: Create token mapping (admin)
- `GET /admin/tokens`: List tokens (admin)
- `DELETE /admin/tokens/{key}`: Delete token (admin)

### 2. Authentication Middleware (`auth.py`)

**Responsibilities**:
- Validate Bearer tokens
- Map MCP API keys to GitHub tokens
- Enforce authentication on protected routes
- Admin token verification

**Security Model**:
```python
# User authentication
Authorization: Bearer mcp_abc123...
  ↓
Validate key exists in token store
  ↓
Retrieve associated GitHub token
  ↓
Use GitHub token for API calls

# Admin authentication
Authorization: Bearer admin_xyz...
  ↓
Validate against MCP_ADMIN_TOKEN
  ↓
Allow token management operations
```

### 3. Token Store (`token_store.py`)

**Responsibilities**:
- Store MCP API key → GitHub token mappings
- Track token metadata (user_id, description, timestamps)
- Provide token lookup and management

**Data Model**:
```python
@dataclass
class TokenMapping:
    mcp_key: str          # "mcp_abc123..."
    github_token: str     # "ghp_xyz..."
    created_at: datetime
    last_used_at: datetime
    user_id: str | None
    description: str | None
```

**Storage**:
- **Current**: In-memory dict with asyncio locks
- **Future**: Redis or PostgreSQL for persistence

**Interface Design**:
```python
class TokenStore(Protocol):
    async def store_token(...) -> None
    async def get_github_token(...) -> str | None
    async def get_mapping(...) -> TokenMapping | None
    async def delete_token(...) -> bool
    async def list_tokens(...) -> list[TokenMapping]
    async def exists(...) -> bool
```

### 4. Rate Limiter (`rate_limiter.py`)

**Responsibilities**:
- Enforce per-user request limits
- Prevent abuse and resource exhaustion
- Track request history with sliding window

**Algorithm**: Sliding Window
- Track individual request timestamps
- Remove expired requests automatically
- Allow configurable burst capacity

**Data Model**:
```python
@dataclass
class RateLimitBucket:
    requests: deque[float]  # Request timestamps
    window_seconds: int     # Time window (60s)
    created_at: float

@dataclass
class RateLimitInfo:
    allowed: bool           # Is request allowed?
    limit: int              # Max requests
    remaining: int          # Requests remaining
    reset_at: float         # When limit resets
    retry_after: float      # Seconds to wait
```

**Cleanup**:
- Background task runs every 5 minutes
- Removes buckets with no recent requests
- Prevents memory leaks

### 5. Configuration (`config.py`)

**Responsibilities**:
- Load and validate configuration
- Provide type-safe settings access
- Support mode-specific requirements

**Key Settings**:
```python
class ServerSettings(BaseSettings):
    # Mode
    mcp_mode: str = "stdio"  # "stdio" or "http"

    # HTTP Server
    mcp_host: str = "0.0.0.0"
    mcp_port: int = 8080

    # Authentication
    mcp_secret_key: SecretStr | None  # Required in http mode
    mcp_admin_token: SecretStr | None

    # GitHub
    github_token: SecretStr | None  # Optional in http mode

    # Rate Limiting
    rate_limit_enabled: bool = True
    rate_limit_requests_per_minute: int = 60
    rate_limit_burst: int = 10

    # CORS
    cors_enabled: bool = True
    cors_allow_origins: str = "*"
```

## Authentication Flow

### User Request Flow

```
1. Client sends request with Bearer token
   ┌──────────────────────────────────────┐
   │ POST /api/fetch-comments             │
   │ Authorization: Bearer mcp_abc123...  │
   └──────────────┬───────────────────────┘
                  ▼
2. Auth middleware validates token
   ┌──────────────────────────────────────┐
   │ verify_mcp_key()                     │
   │  - Parse Bearer token                │
   │  - Check format (length, prefix)     │
   │  - Verify exists in token store      │
   └──────────────┬───────────────────────┘
                  ▼
3. Check rate limit
   ┌──────────────────────────────────────┐
   │ check_rate_limit()                   │
   │  - Count requests in window          │
   │  - Apply limits + burst              │
   │  - Return 429 if exceeded            │
   └──────────────┬───────────────────────┘
                  ▼
4. Get GitHub token
   ┌──────────────────────────────────────┐
   │ get_github_token()                   │
   │  - Lookup in token store             │
   │  - Return GitHub PAT                 │
   └──────────────┬───────────────────────┘
                  ▼
5. Execute MCP logic with GitHub token
   ┌──────────────────────────────────────┐
   │ PRReviewServer.fetch_pr_comments()   │
   │  - Temporarily set GITHUB_TOKEN env  │
   │  - Call existing MCP logic           │
   │  - Restore original env              │
   └──────────────┬───────────────────────┘
                  ▼
6. Return response
```

### Admin Request Flow

```
1. Admin sends request with admin token
   ┌──────────────────────────────────────┐
   │ POST /admin/tokens                   │
   │ Authorization: Bearer admin_xyz...   │
   └──────────────┬───────────────────────┘
                  ▼
2. Verify admin token
   ┌──────────────────────────────────────┐
   │ verify_admin_token()                 │
   │  - Compare with MCP_ADMIN_TOKEN      │
   │  - Return 403 if invalid             │
   └──────────────┬───────────────────────┘
                  ▼
3. Execute admin operation
   ┌──────────────────────────────────────┐
   │ create_token() / list_tokens() etc.  │
   │  - Manipulate token store            │
   │  - Return result                     │
   └──────────────────────────────────────┘
```

## Request Lifecycle

### Example: Fetch PR Comments

```python
# 1. Client request
POST /api/fetch-comments
Authorization: Bearer mcp_abc123...
{
  "pr_url": "https://github.com/owner/repo/pull/123",
  "output": "markdown"
}

# 2. FastAPI receives request
@app.post("/api/fetch-comments")
async def fetch_pr_comments(
    request: FetchCommentsRequest,
    auth: tuple[str, str] = Depends(authenticate_and_rate_limit)
):
    mcp_key, github_token = auth
    # ...

# 3. Dependency: authenticate_and_rate_limit
async def authenticate_and_rate_limit(request: Request):
    # Extract Authorization header
    auth_header = request.headers.get("authorization")

    # Verify MCP API key
    mcp_key = await verify_mcp_key(authorization=auth_header)

    # Check rate limit
    await check_rate_limit(mcp_key)

    # Get GitHub token
    github_token = await get_github_token(mcp_key)

    return mcp_key, github_token

# 4. Execute MCP logic
server = PRReviewServer()
os.environ["GITHUB_TOKEN"] = github_token  # Temporarily set
comments = await server.fetch_pr_review_comments(...)
# Restore original env

# 5. Format response
return FetchCommentsResponse(success=True, data=comments)
```

## Deployment Architecture

### GCP Cloud Run

```
┌─────────────────────────────────────────────┐
│         Cloud Run Service                   │
│  ┌────────────────────────────────────┐    │
│  │  Container Instance                 │    │
│  │  ┌──────────────────────────────┐  │    │
│  │  │  FastAPI App                 │  │    │
│  │  │  Port: 8080                  │  │    │
│  │  │  Health: /health             │  │    │
│  │  └──────────────────────────────┘  │    │
│  └────────────────────────────────────┘    │
│                                              │
│  ┌────────────────────────────────────┐    │
│  │  Environment Variables              │    │
│  │  - MCP_MODE=http                   │    │
│  │  - MCP_SECRET_KEY (from Secret Mgr)│    │
│  │  - MCP_ADMIN_TOKEN (from Secret Mgr│    │
│  └────────────────────────────────────┘    │
└─────────────────────────────────────────────┘
                    │
                    ▼
┌─────────────────────────────────────────────┐
│       Secret Manager                        │
│  - mcp-secret-key                           │
│  - mcp-admin-token                          │
└─────────────────────────────────────────────┘
```

**Benefits**:
- Auto-scaling (0 to N instances)
- Pay-per-use pricing
- Managed HTTPS
- Built-in health checks
- Secret management integration

### Docker Compose (Local)

```
┌─────────────────────────────────────────────┐
│  Docker Network: default                    │
│                                              │
│  ┌────────────────────────────────────┐    │
│  │  mcp-server container               │    │
│  │  Image: github-pr-review-mcp:latest│    │
│  │  Port: 8080:8080                   │    │
│  │  Env: from .env file               │    │
│  └────────────────────────────────────┘    │
└─────────────────────────────────────────────┘
```

## Security Architecture

### Threat Model

**Protected Against**:
- Unauthorized access (API key authentication)
- Brute force (rate limiting)
- Token exposure in logs (SecretStr, prefix logging)
- CORS attacks (configurable origins)
- Resource exhaustion (rate limiting, pagination caps)

**Not Protected Against** (by design):
- DDoS at network layer (use CDN/firewall)
- Token theft (user responsibility)
- GitHub API rate limits (per-token limits)

### Security Layers

```
┌──────────────────────────────────────┐
│  Layer 1: Transport (HTTPS)          │
│  - Managed by platform                │
└──────────────────────────────────────┘
                 ↓
┌──────────────────────────────────────┐
│  Layer 2: CORS                        │
│  - Allowed origins check              │
└──────────────────────────────────────┘
                 ↓
┌──────────────────────────────────────┐
│  Layer 3: Authentication              │
│  - Bearer token validation            │
└──────────────────────────────────────┘
                 ↓
┌──────────────────────────────────────┐
│  Layer 4: Rate Limiting               │
│  - Per-user request limits            │
└──────────────────────────────────────┘
                 ↓
┌──────────────────────────────────────┐
│  Layer 5: Authorization               │
│  - Admin vs user endpoints            │
└──────────────────────────────────────┘
```

## Scalability

### Current Limitations (In-Memory)

- **State**: Lost on restart
- **Scaling**: Single instance only
- **Tokens**: Limited by memory
- **Rate limits**: Not shared across instances

### Redis Migration Path

```python
# 1. Add Redis dependency
dependencies = [..., "redis[hiredis]>=5.0.0"]

# 2. Implement RedisTokenStore
class RedisTokenStore(TokenStore):
    def __init__(self, redis_url: str):
        self.redis = aioredis.from_url(redis_url)

    async def store_token(self, ...):
        await self.redis.hset(
            f"mcp:token:{mcp_key}",
            mapping={
                "github_token": github_token,
                "user_id": user_id,
                ...
            }
        )

# 3. Implement RedisRateLimiter
class RedisRateLimiter(RateLimiter):
    async def check_limit(self, key, limit, window):
        # Use Redis sorted set for sliding window
        now = time.time()
        cutoff = now - window

        pipe = self.redis.pipeline()
        pipe.zremrangebyscore(f"ratelimit:{key}", 0, cutoff)
        pipe.zadd(f"ratelimit:{key}", {str(now): now})
        pipe.zcount(f"ratelimit:{key}", cutoff, now)
        pipe.expire(f"ratelimit:{key}", window)
        results = await pipe.execute()

        count = results[2]
        return RateLimitInfo(allowed=count <= limit, ...)

# 4. Configure at startup
settings = get_settings()
if settings.redis_url:
    token_store = RedisTokenStore(settings.redis_url)
    rate_limiter = RedisRateLimiter(settings.redis_url)
else:
    token_store = InMemoryTokenStore()
    rate_limiter = InMemoryRateLimiter()
```

### Benefits After Redis Migration

- ✅ Persistent state across restarts
- ✅ Horizontal scaling (multiple instances)
- ✅ Shared rate limiting
- ✅ Token expiration (TTL)
- ✅ Distributed locking

## Monitoring

### Key Metrics

1. **Request Metrics**:
   - Total requests per minute
   - Requests by endpoint
   - Response times (p50, p95, p99)
   - Error rate (4xx, 5xx)

2. **Authentication Metrics**:
   - Authentication failures
   - Invalid token attempts
   - Admin API usage

3. **Rate Limiting Metrics**:
   - Rate limit hits
   - Users hitting limits
   - Average requests per user

4. **Resource Metrics**:
   - Memory usage
   - CPU usage
   - Active connections
   - Token store size

### Logging

```python
logger.info("Authentication successful", extra={
    "key_prefix": mcp_key[:8] + "...",
})

logger.warning("Rate limit exceeded", extra={
    "key_prefix": mcp_key[:8] + "...",
    "limit": limit_info.limit,
    "retry_after": limit_info.retry_after,
})

logger.error("GitHub token not found", extra={
    "key_prefix": mcp_key[:8] + "...",
})
```

## Future Enhancements

### Short Term
- [ ] Token expiration and rotation
- [ ] Webhook support for PR events
- [ ] Request/response caching
- [ ] Prometheus metrics endpoint

### Medium Term
- [ ] Redis migration for persistence
- [ ] OAuth2 GitHub integration
- [ ] Multi-tenancy support
- [ ] Audit logging

### Long Term
- [ ] GraphQL API
- [ ] WebSocket support
- [ ] Advanced analytics dashboard
- [ ] Self-service user portal

## References

- [HTTP Deployment Guide](HTTP_DEPLOYMENT.md)
- [Quick Start Guide](HTTP_QUICKSTART.md)
- [MCP Protocol Spec](https://modelcontextprotocol.io/)
- [FastAPI Documentation](https://fastapi.tiangolo.com/)
- [SSE Specification](https://html.spec.whatwg.org/multipage/server-sent-events.html)
