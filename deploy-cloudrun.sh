#!/usr/bin/env bash
# Deployment script for GCP Cloud Run
# Usage: ./deploy-cloudrun.sh [project-id] [region]

set -euo pipefail

# Configuration
PROJECT_ID="${1:-}"
REGION="${2:-us-central1}"
SERVICE_NAME="github-pr-review-mcp"
IMAGE_NAME="gcr.io/${PROJECT_ID}/${SERVICE_NAME}"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Helper functions
log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check prerequisites
check_prereqs() {
    log_info "Checking prerequisites..."

    # Check for gcloud
    if ! command -v gcloud &> /dev/null; then
        log_error "gcloud CLI not found. Install from: https://cloud.google.com/sdk/docs/install"
        exit 1
    fi

    # Check for docker
    if ! command -v docker &> /dev/null; then
        log_error "docker not found. Install from: https://docs.docker.com/get-docker/"
        exit 1
    fi

    # Validate project ID
    if [ -z "$PROJECT_ID" ]; then
        log_error "Project ID is required. Usage: $0 <project-id> [region]"
        exit 1
    fi

    log_info "Prerequisites check passed"
}

# Configure gcloud
configure_gcloud() {
    log_info "Configuring gcloud..."

    gcloud config set project "$PROJECT_ID"
    gcloud config set run/region "$REGION"

    # Enable required APIs
    log_info "Enabling required APIs..."
    gcloud services enable \
        run.googleapis.com \
        containerregistry.googleapis.com \
        secretmanager.googleapis.com \
        --project="$PROJECT_ID"
}

# Create secrets if they don't exist
create_secrets() {
    log_info "Checking secrets..."

    # MCP_SECRET_KEY
    if ! gcloud secrets describe mcp-secret-key --project="$PROJECT_ID" &> /dev/null; then
        log_warn "Secret 'mcp-secret-key' not found. Creating..."
        echo -n "$(openssl rand -base64 32)" | \
            gcloud secrets create mcp-secret-key \
                --data-file=- \
                --project="$PROJECT_ID"
        log_info "Created mcp-secret-key"
    else
        log_info "Secret 'mcp-secret-key' already exists"
    fi

    # MCP_ADMIN_TOKEN (optional)
    if ! gcloud secrets describe mcp-admin-token --project="$PROJECT_ID" &> /dev/null; then
        log_warn "Secret 'mcp-admin-token' not found. Creating..."
        echo -n "admin_$(openssl rand -base64 24)" | \
            gcloud secrets create mcp-admin-token \
                --data-file=- \
                --project="$PROJECT_ID"
        log_info "Created mcp-admin-token"
    else
        log_info "Secret 'mcp-admin-token' already exists"
    fi
}

# Build and push Docker image
build_and_push() {
    log_info "Building Docker image..."

    docker build -t "$IMAGE_NAME:latest" .

    log_info "Pushing image to GCR..."
    docker push "$IMAGE_NAME:latest"

    log_info "Image pushed successfully"
}

# Deploy to Cloud Run
deploy() {
    log_info "Deploying to Cloud Run..."

    # Update cloudrun.yaml with project ID
    sed "s/PROJECT_ID/${PROJECT_ID}/g" cloudrun.yaml > cloudrun-deployed.yaml

    # Deploy using gcloud
    gcloud run services replace cloudrun-deployed.yaml \
        --region="$REGION" \
        --project="$PROJECT_ID"

    # Clean up temporary file
    rm cloudrun-deployed.yaml

    # Get service URL
    SERVICE_URL=$(gcloud run services describe "$SERVICE_NAME" \
        --region="$REGION" \
        --project="$PROJECT_ID" \
        --format="value(status.url)")

    log_info "Deployment complete!"
    echo ""
    echo "Service URL: $SERVICE_URL"
    echo "Health check: $SERVICE_URL/health"
    echo "API docs: $SERVICE_URL/docs"
    echo ""
    log_info "To view logs: gcloud run services logs tail $SERVICE_NAME --region=$REGION --project=$PROJECT_ID"
}

# Main execution
main() {
    log_info "Starting deployment to GCP Cloud Run"
    log_info "Project: $PROJECT_ID"
    log_info "Region: $REGION"
    echo ""

    check_prereqs
    configure_gcloud
    create_secrets
    build_and_push
    deploy

    log_info "All done! 🎉"
}

# Run main function
main
