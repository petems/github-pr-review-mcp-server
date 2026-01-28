#!/usr/bin/env python3
"""Test script for MCP HTTP streaming server."""

import asyncio
import json

import httpx


async def test_mcp_http_server():
    """Test the MCP HTTP server with proper protocol flow."""
    base_url = "http://127.0.0.1:8000"

    # Required headers for MCP HTTP protocol
    # NOTE: MCP protocol requires BOTH accept types even though we only use JSON
    common_headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        # Step 1: Initialize the connection
        print("1. Testing initialize...")
        init_response = await client.post(
            base_url,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "test-client", "version": "1.0.0"},
                },
            },
            headers=common_headers,
        )
        print(f"Status: {init_response.status_code}")
        print(f"Response: {json.dumps(init_response.json(), indent=2)}\n")

        # Step 2: Send initialized notification
        print("2. Sending initialized notification...")
        notif_response = await client.post(
            base_url,
            json={
                "jsonrpc": "2.0",
                "method": "notifications/initialized",
            },
            headers=common_headers,
        )
        print(f"Status: {notif_response.status_code}\n")

        # Step 3: List available tools
        print("3. Listing tools...")
        tools_response = await client.post(
            base_url,
            json={
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/list",
            },
            headers=common_headers,
        )
        print(f"Status: {tools_response.status_code}")
        tools_data = tools_response.json()
        print(f"Response: {json.dumps(tools_data, indent=2)}\n")

        # Step 4: Call a tool (resolve_open_pr_url)
        print("4. Testing resolve_open_pr_url tool...")
        tool_response = await client.post(
            base_url,
            json={
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {
                    "name": "resolve_open_pr_url",
                    "arguments": {
                        "owner": "cool-kids-inc",
                        "repo": "github-pr-review-mcp-server",
                        "branch": "main",
                        "select_strategy": "latest",
                    },
                },
            },
            headers=common_headers,
        )
        print(f"Status: {tool_response.status_code}")
        print(f"Response: {json.dumps(tool_response.json(), indent=2)}\n")

        print("✅ All MCP HTTP tests completed successfully!")


if __name__ == "__main__":
    print("Starting MCP HTTP server tests...")
    print("Make sure the server is running: uv run mcp-github-pr-review http\n")
    asyncio.run(test_mcp_http_server())
