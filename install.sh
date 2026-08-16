#!/bin/bash

# Installation script for Local Network MCP Server

echo "Installing dependencies for Local Network MCP Server..."
echo "=================================================="

cd "$(dirname "$0")"

# Check if pip is available
if ! command -v pip3 &> /dev/null; then
    echo "Error: pip3 not found. Please install Python 3 with pip."
    exit 1
fi

# Install requirements
echo "Installing Python packages..."
pip3 install -r requirements.txt

# Check if installation was successful
if [ $? -eq 0 ]; then
    echo ""
    echo "✅ Installation successful!"
    echo ""
    echo "Testing the server..."
    timeout 3 python3 network_mcp_server.py &
    sleep 2
    echo ""
    echo "If no errors appeared above, the server is ready!"
    echo ""
    echo "Next steps:"
    echo "1. Restart Claude Desktop completely (quit and reopen)"
    echo "2. Ask Claude to scan your network"
else
    echo ""
    echo "❌ Installation failed. Please check the error messages above."
fi
