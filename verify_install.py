#!/usr/bin/env python
"""
Verification script for PyMOL MCP Bridge installation.

This script checks that all components are properly installed and configured.

Usage:
    python verify_install.py
"""

import sys
import os
from pathlib import Path


def check_python_version():
    """Check Python version is >= 3.8."""
    print("Checking Python version...")
    version = sys.version_info
    if version.major >= 3 and version.minor >= 8:
        print(f"✓ Python {version.major}.{version.minor}.{version.micro}")
        return True
    else:
        print(f"❌ Python {version.major}.{version.minor}.{version.micro} (requires >= 3.8)")
        return False


def check_dependencies():
    """Check required dependencies are installed."""
    print("\nChecking dependencies...")
    
    dependencies = {
        "fastmcp": "FastMCP",
        "yaml": "PyYAML",
    }
    
    all_ok = True
    for module, name in dependencies.items():
        try:
            __import__(module)
            print(f"✓ {name} installed")
        except ImportError:
            print(f"❌ {name} not installed")
            all_ok = False
    
    return all_ok


def check_package_structure():
    """Check package structure is correct."""
    print("\nChecking package structure...")
    
    required_files = [
        "pymol_mcp/__init__.py",
        "pymol_mcp/server.py",
        "pymol_mcp/client.py",
        "pymol_mcp/config.py",
        "pymol_mcp/tools.py",
        "pymol_plugin/__init__.py",
        "requirements.txt",
        "pyproject.toml",
        "README.md",
    ]
    
    base_dir = Path(__file__).parent
    all_ok = True
    
    for file_path in required_files:
        full_path = base_dir / file_path
        if full_path.exists():
            print(f"✓ {file_path}")
        else:
            print(f"❌ {file_path} missing")
            all_ok = False
    
    return all_ok


def check_pymol_mcp_import():
    """Check pymol_mcp package can be imported."""
    print("\nChecking pymol_mcp package...")
    
    try:
        import pymol_mcp
        print(f"✓ pymol_mcp package importable (version {pymol_mcp.__version__})")
        
        from pymol_mcp import config, client, tools
        print("✓ All submodules importable")
        
        return True
    except ImportError as e:
        print(f"❌ Cannot import pymol_mcp: {e}")
        print("   Run: pip install -e .")
        return False


def check_server_command():
    """Check server can be invoked."""
    print("\nChecking server command...")
    
    try:
        from pymol_mcp.server import main
        print("✓ Server entry point accessible")
        return True
    except ImportError as e:
        print(f"❌ Cannot import server: {e}")
        return False


def check_plugin_file():
    """Check PyMOL plugin file exists and is valid."""
    print("\nChecking PyMOL plugin...")
    
    base_dir = Path(__file__).parent
    plugin_path = base_dir / "pymol_plugin" / "__init__.py"
    
    if not plugin_path.exists():
        print("❌ Plugin file not found")
        return False
    
    try:
        with open(plugin_path, 'r') as f:
            content = f.read()
            
        required_functions = [
            "__init_plugin__",
            "start_server",
            "stop_server",
            "show_status",
        ]
        
        all_ok = True
        for func in required_functions:
            if func in content:
                print(f"✓ Plugin has {func}()")
            else:
                print(f"❌ Plugin missing {func}()")
                all_ok = False
        
        return all_ok
    
    except Exception as e:
        print(f"❌ Error reading plugin: {e}")
        return False


def check_documentation():
    """Check documentation files exist."""
    print("\nChecking documentation...")
    
    docs = [
        "README.md",
        "QUICKSTART.md",
        "PLUGIN_INSTALL.md",
        "MCP_CONFIG.md",
        "PROJECT_SUMMARY.md",
    ]
    
    base_dir = Path(__file__).parent
    all_ok = True
    
    for doc in docs:
        if (base_dir / doc).exists():
            print(f"✓ {doc}")
        else:
            print(f"❌ {doc} missing")
            all_ok = False
    
    return all_ok


def check_tests():
    """Check test files exist."""
    print("\nChecking tests...")
    
    tests = [
        "tests/__init__.py",
        "tests/test_protocol.py",
        "tests/test_client.py",
        "tests/test_tools.py",
        "tests/integration_test.py",
    ]
    
    base_dir = Path(__file__).parent
    all_ok = True
    
    for test in tests:
        if (base_dir / test).exists():
            print(f"✓ {test}")
        else:
            print(f"❌ {test} missing")
            all_ok = False
    
    return all_ok


def main():
    """Run all verification checks."""
    print("=" * 60)
    print("PyMOL MCP Bridge - Installation Verification")
    print("=" * 60)
    
    checks = [
        ("Python Version", check_python_version),
        ("Dependencies", check_dependencies),
        ("Package Structure", check_package_structure),
        ("PyMOL MCP Import", check_pymol_mcp_import),
        ("Server Command", check_server_command),
        ("PyMOL Plugin", check_plugin_file),
        ("Documentation", check_documentation),
        ("Tests", check_tests),
    ]
    
    results = []
    for name, check_func in checks:
        try:
            success = check_func()
            results.append((name, success))
        except Exception as e:
            print(f"❌ {name} check failed with exception: {e}")
            results.append((name, False))
    
    print("\n" + "=" * 60)
    print("Verification Summary")
    print("=" * 60)
    
    passed = sum(1 for _, success in results if success)
    total = len(results)
    
    for name, success in results:
        status = "✓ PASS" if success else "❌ FAIL"
        print(f"{status}: {name}")
    
    print(f"\nTotal: {passed}/{total} checks passed")
    
    if passed == total:
        print("\n🎉 Installation verified successfully!")
        print("\nNext steps:")
        print("1. Install PyMOL plugin (see PLUGIN_INSTALL.md)")
        print("2. Configure MCP client (see MCP_CONFIG.md)")
        print("3. Start PyMOL and enable plugin")
        print("4. Test with: python tests/integration_test.py")
        return 0
    else:
        print(f"\n⚠️  {total - passed} check(s) failed")
        print("\nTo fix:")
        print("1. Install dependencies: pip install -e .")
        print("2. Check all files are present")
        print("3. Run this script again")
        return 1


if __name__ == "__main__":
    sys.exit(main())
