# Multi-stage Dockerfile for GitHub PR Review MCP Server
# Optimized for GCP Cloud Run deployment with minimal image size

# Stage 1: Builder - Install dependencies
FROM python:3.11-slim as builder

# Install uv for fast dependency resolution
RUN pip install --no-cache-dir uv

# Set working directory
WORKDIR /app

# Copy dependency files
COPY pyproject.toml ./

# Install dependencies using uv (creates .venv)
RUN uv pip install --system --no-cache -e .

# Stage 2: Runtime - Minimal image
FROM python:3.11-slim

# Create non-root user for security
RUN useradd --create-home --shell /bin/bash appuser

# Set working directory
WORKDIR /app

# Copy Python dependencies from builder
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy application code
COPY src ./src
COPY pyproject.toml ./

# Install application in editable mode (for importlib.metadata version detection)
RUN pip install --no-cache-dir --no-deps -e .

# Change ownership to non-root user
RUN chown -R appuser:appuser /app

# Switch to non-root user
USER appuser

# Expose port (Cloud Run uses PORT env var, default 8080)
ENV PORT=8080
EXPOSE 8080

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:${PORT}/health').read()" || exit 1

# Set environment defaults for HTTP mode
ENV MCP_MODE=http
ENV MCP_HOST=0.0.0.0
ENV MCP_PORT=8080

# Run the HTTP server
CMD ["python", "-m", "mcp_github_pr_review.http_server"]
