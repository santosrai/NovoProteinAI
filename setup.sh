#!/bin/bash
# Setup script for PyMOL MCP Bridge

set -e

echo "============================================================"
echo "PyMOL MCP Bridge - Setup"
echo "============================================================"

# Check Python version
echo ""
echo "Checking Python..."
if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 not found. Please install Python 3.8 or higher."
    exit 1
fi

PYTHON_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
echo "✓ Python $PYTHON_VERSION found"

# Install dependencies
echo ""
echo "Installing dependencies..."
python3 -m pip install -e . || {
    echo "❌ Failed to install dependencies"
    echo "Try: python3 -m pip install --user -e ."
    exit 1
}

echo "✓ Dependencies installed"

# Verify installation
echo ""
echo "Verifying installation..."
python3 verify_install.py || {
    echo "⚠️  Verification found issues"
    exit 1
}

echo ""
echo "============================================================"
echo "Setup Complete!"
echo "============================================================"
echo ""
echo "Next steps:"
echo ""
echo "1. Install PyMOL Plugin:"
echo "   - Open PyMOL"
echo "   - Plugin → Plugin Manager → Install New Plugin"
echo "   - Select: pymol_plugin/__init__.py"
echo "   - Restart PyMOL"
echo ""
echo "2. Start PyMOL Plugin:"
echo "   - Plugin → agentic-pymol plugin → Start Listening"
echo ""
echo "3. Configure MCP Client:"
echo "   - See MCP_CONFIG.md for your client (Claude Desktop, Cline, etc.)"
echo ""
echo "4. Test Installation:"
echo "   python3 tests/integration_test.py"
echo ""
echo "For more information, see:"
echo "  - QUICKSTART.md - Quick start guide"
echo "  - README.md - Full documentation"
echo "  - PLUGIN_INSTALL.md - Plugin installation details"
echo ""
