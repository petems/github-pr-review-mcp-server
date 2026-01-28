#!/usr/bin/env bash
# OAuth Setup Helper Script
# Helps determine the correct callback URL and configure OAuth

set -euo pipefail

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}           GitHub OAuth Setup Helper                          ${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""

# Step 1: Determine deployment type
echo -e "${YELLOW}Step 1: Choose your deployment type${NC}"
echo ""
echo "1) Local development (ngrok)"
echo "2) Local development (localhost - testing only)"
echo "3) GCP Cloud Run"
echo "4) Render.com"
echo "5) Custom domain"
echo "6) Hugging Face Spaces"
echo ""
read -p "Enter choice [1-6]: " choice
echo ""

# Generate callback URL based on choice
case $choice in
    1)
        echo -e "${YELLOW}Local Development with ngrok${NC}"
        echo ""
        echo "To use ngrok:"
        echo "  1. Install: brew install ngrok"
        echo "  2. Start server: uv run python -m mcp_github_pr_review.http_server"
        echo "  3. In new terminal: ngrok http 8080"
        echo "  4. Copy the https URL (e.g., https://abc123.ngrok.io)"
        echo ""
        read -p "Enter your ngrok URL (e.g., https://abc123.ngrok.io): " base_url
        CALLBACK_URL="${base_url}/auth/callback"
        ;;
    2)
        echo -e "${YELLOW}Local Development (localhost)${NC}"
        echo ""
        echo -e "${RED}WARNING: Only use this for local testing!${NC}"
        echo "This will NOT work in production."
        echo ""
        CALLBACK_URL="http://localhost:8080/auth/callback"
        ;;
    3)
        echo -e "${YELLOW}GCP Cloud Run${NC}"
        echo ""
        echo "Checking if you have a deployed service..."
        if command -v gcloud &> /dev/null; then
            echo "Enter your project ID and service name:"
            read -p "Project ID: " project_id
            read -p "Service name [github-pr-review-mcp]: " service_name
            service_name=${service_name:-github-pr-review-mcp}
            read -p "Region [us-central1]: " region
            region=${region:-us-central1}

            # Try to get the URL
            if url=$(gcloud run services describe "$service_name" \
                --region="$region" \
                --project="$project_id" \
                --format="value(status.url)" 2>/dev/null); then
                echo -e "${GREEN}Found deployed service!${NC}"
                CALLBACK_URL="${url}/auth/callback"
            else
                echo -e "${YELLOW}Service not found. Enter manually:${NC}"
                read -p "Service URL (e.g., https://service-abc-uc.a.run.app): " base_url
                CALLBACK_URL="${base_url}/auth/callback"
            fi
        else
            echo "gcloud not found. Enter your Cloud Run URL manually:"
            read -p "Service URL (e.g., https://service-abc-uc.a.run.app): " base_url
            CALLBACK_URL="${base_url}/auth/callback"
        fi
        ;;
    4)
        echo -e "${YELLOW}Render.com${NC}"
        echo ""
        read -p "Enter your Render app name: " app_name
        CALLBACK_URL="https://${app_name}.onrender.com/auth/callback"
        ;;
    5)
        echo -e "${YELLOW}Custom Domain${NC}"
        echo ""
        read -p "Enter your domain (e.g., mcp.example.com): " domain
        CALLBACK_URL="https://${domain}/auth/callback"
        ;;
    6)
        echo -e "${YELLOW}Hugging Face Spaces${NC}"
        echo ""
        read -p "Enter your username: " username
        read -p "Enter space name: " space_name
        CALLBACK_URL="https://huggingface.co/spaces/${username}/${space_name}/auth/callback"
        ;;
    *)
        echo -e "${RED}Invalid choice${NC}"
        exit 1
        ;;
esac

echo ""
echo -e "${GREEN}✓ Callback URL determined:${NC}"
echo -e "${BLUE}  ${CALLBACK_URL}${NC}"
echo ""

# Step 2: GitHub OAuth App setup
echo -e "${YELLOW}Step 2: Register GitHub OAuth App${NC}"
echo ""
echo "1. Open: https://github.com/settings/developers"
echo "2. Click: 'New OAuth App'"
echo "3. Fill in:"
echo "   Application name: MCP PR Review Server"
echo "   Homepage URL: ${base_url:-http://localhost:8080}"
echo -e "   ${GREEN}Authorization callback URL: ${CALLBACK_URL}${NC}"
echo "4. Click 'Register application'"
echo "5. Generate a client secret"
echo ""
read -p "Press Enter when you've registered the app..."
echo ""

# Step 3: Get OAuth credentials
echo -e "${YELLOW}Step 3: Enter OAuth Credentials${NC}"
echo ""
read -p "GitHub OAuth Client ID (Iv1.xxx): " client_id
read -sp "GitHub OAuth Client Secret: " client_secret
echo ""
echo ""

# Step 4: Generate other secrets
echo -e "${YELLOW}Step 4: Generate Server Secrets${NC}"
echo ""
mcp_secret=$(openssl rand -base64 32)
admin_token=$(openssl rand -base64 32)
echo -e "${GREEN}✓ Generated MCP_SECRET_KEY${NC}"
echo -e "${GREEN}✓ Generated MCP_ADMIN_TOKEN${NC}"
echo ""

# Step 5: Create .env file
echo -e "${YELLOW}Step 5: Creating .env file${NC}"
echo ""

cat > .env.oauth <<EOF
# OAuth Configuration
# Generated by setup-oauth.sh on $(date)

# Server Configuration
MCP_MODE=http
MCP_HOST=0.0.0.0
MCP_PORT=8080
MCP_SECRET_KEY=$mcp_secret
MCP_ADMIN_TOKEN=$admin_token

# OAuth Configuration
GITHUB_OAUTH_ENABLED=true
GITHUB_OAUTH_CLIENT_ID=$client_id
GITHUB_OAUTH_CLIENT_SECRET=$client_secret
GITHUB_OAUTH_CALLBACK_URL=$CALLBACK_URL
GITHUB_OAUTH_SCOPES=repo,read:user

# Rate Limiting
RATE_LIMIT_ENABLED=true
RATE_LIMIT_REQUESTS_PER_MINUTE=60
RATE_LIMIT_BURST=10

# CORS
CORS_ENABLED=true
CORS_ALLOW_ORIGINS=*
CORS_ALLOW_CREDENTIALS=true
EOF

echo -e "${GREEN}✓ Created .env.oauth${NC}"
echo ""

# Step 6: Summary
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN}                    Setup Complete!                           ${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
echo "Configuration saved to: .env.oauth"
echo ""
echo -e "${YELLOW}Callback URL (use this in GitHub OAuth App):${NC}"
echo -e "${BLUE}  ${CALLBACK_URL}${NC}"
echo ""
echo -e "${YELLOW}Next Steps:${NC}"
echo "1. Copy .env.oauth to .env:"
echo "   cp .env.oauth .env"
echo ""
echo "2. Start the server:"
echo "   source .env && uv run python -m mcp_github_pr_review.http_server"
echo ""
echo "3. Test OAuth flow:"
echo "   Visit: ${base_url:-http://localhost:8080}/auth/login"
echo ""
echo -e "${YELLOW}Important URLs:${NC}"
echo "  Login:    ${base_url:-http://localhost:8080}/auth/login"
echo "  Callback: ${CALLBACK_URL}"
echo "  Status:   ${base_url:-http://localhost:8080}/auth/status"
echo "  Docs:     ${base_url:-http://localhost:8080}/docs"
echo ""
echo -e "${GREEN}Happy OAuth-ing! 🚀${NC}"
echo ""
