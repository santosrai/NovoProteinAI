# PyMOL Plugin Installation Guide

This guide covers installing the PyMOL MCP Bridge plugin into PyMOL.

## Prerequisites

- PyMOL installed (open-source or commercial)
- Python 3.8 or higher
- PyMOL with Python plugin support

## Installation Methods

### Method 1: Plugin Manager (Recommended)

1. **Open PyMOL**

2. **Open Plugin Manager**
   - Go to `Plugin` → `Plugin Manager` in the menu bar

3. **Install Plugin**
   - Click the `Install New Plugin` tab
   - Click `Choose file...`
   - Navigate to `pymol_plugin/__init__.py` in this repository
   - Click `Open`

4. **Select Installation Location**
   - Choose installation directory (default is usually fine)
   - Click `OK`

5. **Restart PyMOL**
   - Close and reopen PyMOL for the plugin to load

6. **Verify Installation**
   - Look for `agentic-pymol plugin` in the `Plugin` menu
   - You should see four menu items:
     - Control Panel
     - Start Server
     - Stop Server
     - Server Status

### Method 2: Manual Installation

1. **Locate PyMOL Plugin Directory**

   Find your PyMOL plugin directory:
   
   - **macOS**: `~/Library/Application Support/PyMOL/startup/`
   - **Linux**: `~/.pymol/startup/`
   - **Windows**: `%USERPROFILE%\pymol\startup\`

2. **Copy Plugin File**

   ```bash
   # macOS/Linux
   cp pymol_plugin/__init__.py ~/Library/Application\ Support/PyMOL/startup/pymol_mcp_plugin.py
   
   # Or create symlink for development
   ln -s $(pwd)/pymol_plugin/__init__.py ~/Library/Application\ Support/PyMOL/startup/pymol_mcp_plugin.py
   ```

3. **Restart PyMOL**

4. **Verify Installation**
   - Check `Plugin` menu for `agentic-pymol plugin`

### Method 3: Run Command in PyMOL

1. **Open PyMOL**

2. **Run in PyMOL Console**
   ```python
   run /path/to/pymol_plugin/__init__.py
   ```

3. **Initialize Plugin**
   ```python
   __init_plugin__()
   ```

Note: This method requires running the commands each time you start PyMOL.

## Usage

### Control Panel (Recommended)

1. Go to `Plugin` → `agentic-pymol plugin` → `Control Panel`
2. A window opens showing:
   - **Server Status** — Running/Stopped indicator, port, connected client count (auto-refreshes every second)
   - **Start / Stop Server** buttons
   - **Activity Log** — live stream of client connections and MCP tool calls

Click **Start Server** to begin listening, then watch the activity log as your MCP client connects.

### Menu Commands (Fallback)

If Qt is unavailable, use the console-based menu commands:

1. **Start Server**
   - `Plugin` → `agentic-pymol plugin` → `Start Server`
   - Console shows: `PyMOL MCP Plugin: Server started on localhost:9877`

2. **Check Status**
   - `Plugin` → `agentic-pymol plugin` → `Server Status`

3. **Stop Server**
   - `Plugin` → `agentic-pymol plugin` → `Stop Server`

## Configuration

### Changing the Port

By default, the plugin listens on port `9877`. To change this:

1. **Edit the plugin file** (`pymol_plugin/__init__.py`)

2. **Modify the default port** in the `start_server()` function:
   ```python
   _server_instance = PyMOLTCPServer(port=YOUR_PORT)
   ```

3. **Update MCP server configuration** to match the new port

## Troubleshooting

### Plugin Menu Not Appearing

**Problem**: `agentic-pymol plugin` doesn't appear in Plugin menu

**Solutions**:
1. Check PyMOL console for error messages
2. Verify Python version: `python --version` (should be ≥3.8)
3. Ensure PyMOL has plugin support enabled
4. Try reinstalling with Method 1

### Server Won't Start

**Problem**: "Failed to start server" error

**Solutions**:
1. Check if port 9877 is already in use:
   ```bash
   # macOS/Linux
   lsof -i :9877
   
   # Windows
   netstat -ano | findstr :9877
   ```
2. Kill the process using the port or change the plugin port
3. Check firewall settings

### Import Errors

**Problem**: `ImportError` or `ModuleNotFoundError` in PyMOL console

**Solutions**:
1. Verify PyMOL's Python environment has required modules
2. Standard library modules should be available (socket, json, threading)
3. If using conda/virtual env, ensure PyMOL uses the correct Python

### Plugin Loads but Commands Fail

**Problem**: Plugin menu appears but commands don't execute

**Solutions**:
1. Check PyMOL console for error messages
2. Verify PyMOL `cmd` module is available:
   ```python
   # In PyMOL console
   from pymol import cmd
   print(cmd.get_version())
   ```
3. Try running a simple PyMOL command to verify functionality

## Uninstallation

### Method 1: Plugin Manager

1. Open PyMOL
2. Go to `Plugin` → `Plugin Manager`
3. Find `pymol_mcp_plugin` in the list
4. Click `Remove`
5. Restart PyMOL

### Method 2: Manual

1. Delete the plugin file from PyMOL's startup directory:
   ```bash
   # macOS
   rm ~/Library/Application\ Support/PyMOL/startup/pymol_mcp_plugin.py
   
   # Linux
   rm ~/.pymol/startup/pymol_mcp_plugin.py
   ```

2. Restart PyMOL

## Development Mode

For plugin development, use a symlink instead of copying:

```bash
# macOS/Linux
ln -s $(pwd)/pymol_plugin/__init__.py ~/Library/Application\ Support/PyMOL/startup/pymol_mcp_plugin.py
```

This allows you to edit the plugin file and see changes after restarting PyMOL.

## Testing the Plugin

### Basic Test

1. Start PyMOL
2. Start the plugin server
3. In a separate terminal:
   ```bash
   # Test connection
   echo '{"jsonrpc":"2.0","method":"ping","params":{},"id":1}' | nc localhost 9877
   ```
4. You should receive a JSON response

### Integration Test

1. Start PyMOL and the plugin
2. Run the MCP server:
   ```bash
   python -m pymol_mcp.server
   ```
3. The MCP server should connect successfully

## Support

If you encounter issues:

1. Check the PyMOL console for error messages
2. Review the [Troubleshooting](#troubleshooting) section
3. Check server logs (if running MCP server)
4. Open an issue on GitHub with:
   - PyMOL version
   - Python version
   - Error messages
   - Steps to reproduce
