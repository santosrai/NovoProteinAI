#!/usr/bin/env python
"""
Integration test for PyMOL MCP Bridge.

This script tests the full stack:
1. PyMOL plugin TCP server
2. MCP client connection
3. All 5 MCP tools

Prerequisites:
- PyMOL running with plugin started
- Plugin listening on localhost:9877

Usage:
    python tests/integration_test.py
"""

import sys
import time
from pymol_mcp.config import PyMOLConfig
from pymol_mcp.client import PyMOLClient
from pymol_mcp import tools


def test_connection():
    """Test basic connection to PyMOL."""
    print("Testing connection...")
    
    config = PyMOLConfig.load()
    client = PyMOLClient(config)
    
    if not client.connect():
        print("❌ Failed to connect to PyMOL")
        print("   Make sure PyMOL is running and plugin is started:")
        print("   Plugin → agentic-pymol plugin → Control Panel → Start Server")
        return False
    
    print("✓ Connected to PyMOL")
    client.disconnect()
    return True


def test_ping():
    """Test ping tool."""
    print("\nTesting ping_pymol...")
    
    try:
        result = tools.ping_pymol()
        print(f"✓ {result}")
        return True
    except Exception as e:
        print(f"❌ ping_pymol failed: {e}")
        return False


def test_load_structure():
    """Test load_structure tool."""
    print("\nTesting load_structure...")
    
    try:
        result = tools.load_structure("1ABC", "test_protein")
        print(f"✓ {result}")
        return True
    except Exception as e:
        print(f"❌ load_structure failed: {e}")
        return False


def test_select_atoms():
    """Test select_atoms tool."""
    print("\nTesting select_atoms...")
    
    try:
        result = tools.select_atoms("test_selection", "chain A")
        print(f"✓ {result}")
        return True
    except Exception as e:
        print(f"❌ select_atoms failed: {e}")
        return False


def test_color_selection():
    """Test color_selection tool."""
    print("\nTesting color_selection...")
    
    try:
        result = tools.color_selection("red", "test_selection")
        print(f"✓ {result}")
        return True
    except Exception as e:
        print(f"❌ color_selection failed: {e}")
        return False


def test_render_image():
    """Test render_image tool."""
    print("\nTesting render_image...")
    
    import tempfile
    import os
    
    try:
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            output_path = f.name
        
        result = tools.render_image(output_path, width=400, height=300)
        print(f"✓ {result}")
        
        if os.path.exists(output_path):
            size = os.path.getsize(output_path)
            print(f"  Image file created: {size} bytes")
            os.unlink(output_path)
            return True
        else:
            print(f"❌ Image file not created: {output_path}")
            return False
    
    except Exception as e:
        print(f"❌ render_image failed: {e}")
        return False


def main():
    """Run all integration tests."""
    print("=" * 60)
    print("PyMOL MCP Bridge - Integration Test")
    print("=" * 60)
    
    tests = [
        ("Connection", test_connection),
        ("Ping", test_ping),
        ("Load Structure", test_load_structure),
        ("Select Atoms", test_select_atoms),
        ("Color Selection", test_color_selection),
        ("Render Image", test_render_image),
    ]
    
    results = []
    for name, test_func in tests:
        try:
            success = test_func()
            results.append((name, success))
        except Exception as e:
            print(f"❌ {name} test crashed: {e}")
            results.append((name, False))
        
        time.sleep(0.5)
    
    print("\n" + "=" * 60)
    print("Test Results")
    print("=" * 60)
    
    passed = sum(1 for _, success in results if success)
    total = len(results)
    
    for name, success in results:
        status = "✓ PASS" if success else "❌ FAIL"
        print(f"{status}: {name}")
    
    print(f"\nTotal: {passed}/{total} tests passed")
    
    if passed == total:
        print("\n🎉 All tests passed!")
        return 0
    else:
        print(f"\n⚠️  {total - passed} test(s) failed")
        return 1


if __name__ == "__main__":
    sys.exit(main())
