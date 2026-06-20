# MCP Client Configuration Guide

This guide covers configuring various MCP clients to use the PyMOL MCP Bridge.

## Prerequisites

- PyMOL MCP Bridge installed (`pip install -e .`)
- PyMOL running with plugin started
- MCP client installed (Claude Desktop, Cline, etc.)

## Claude Desktop

### Configuration File Location

- **macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`
- **Windows**: `%APPDATA%\Claude\claude_desktop_config.json`
- **Linux**: `~/.config/Claude/claude_desktop_config.json`

### Basic Configuration

```json
{
  "mcpServers": {
    "pymol": {
      "command": "python",
      "args": ["-m", "pymol_mcp.server"]
    }
  }
}
```

### With Custom Configuration

```json
{
  "mcpServers": {
    "pymol": {
      "command": "python",
      "args": ["-m", "pymol_mcp.server"],
      "env": {
        "PYMOL_HOST": "localhost",
        "PYMOL_PORT": "9877",
        "PYMOL_TIMEOUT": "30.0",
        "PYMOL_LOG_LEVEL": "INFO"
      }
    }
  }
}
```

### With Virtual Environment

```json
{
  "mcpServers": {
    "pymol": {
      "command": "/path/to/venv/bin/python",
      "args": ["-m", "pymol_mcp.server"]
    }
  }
}
```

### With Config File

```json
{
  "mcpServers": {
    "pymol": {
      "command": "python",
      "args": ["-m", "pymol_mcp.server", "--config", "/path/to/config.yaml"]
    }
  }
}
```

### Restart Claude Desktop

After editing the config file, restart Claude Desktop for changes to take effect.

## Cline (VS Code Extension)

### Configuration

1. Open VS Code
2. Go to Settings → Extensions → Cline
3. Add MCP server configuration:

```json
{
  "mcpServers": {
    "pymol": {
      "command": "python",
      "args": ["-m", "pymol_mcp.server"],
      "env": {
        "PYMOL_HOST": "localhost",
        "PYMOL_PORT": "9877"
      }
    }
  }
}
```

## Devin / Cognition

### Configuration

Add to your Devin workspace configuration:

```json
{
  "mcp": {
    "servers": {
      "pymol": {
        "command": "python",
        "args": ["-m", "pymol_mcp.server"],
        "env": {
          "PYMOL_HOST": "localhost",
          "PYMOL_PORT": "9877"
        }
      }
    }
  }
}
```

## Generic MCP Client

For any MCP client that supports stdio transport:

### Command Line

```bash
python -m pymol_mcp.server
```

### With Environment Variables

```bash
PYMOL_HOST=localhost PYMOL_PORT=9877 python -m pymol_mcp.server
```

### With Config File

```bash
python -m pymol_mcp.server --config config.yaml
```

## Configuration Options

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `PYMOL_HOST` | `localhost` | PyMOL plugin host |
| `PYMOL_PORT` | `9877` | PyMOL plugin port |
| `PYMOL_TIMEOUT` | `30.0` | Request timeout (seconds) |
| `PYMOL_RECONNECT_ATTEMPTS` | `3` | Number of reconnection attempts |
| `PYMOL_RECONNECT_DELAY` | `1.0` | Initial reconnection delay (seconds) |
| `PYMOL_LOG_LEVEL` | `INFO` | Logging level (DEBUG, INFO, WARNING, ERROR) |

### Config File (YAML)

Create `config.yaml`:

```yaml
host: localhost
port: 9877
timeout: 30.0
reconnect_attempts: 3
reconnect_delay: 1.0
log_level: INFO
```

## Verification

### Check MCP Server is Running

The MCP server should start automatically when the client launches. Check logs:

```bash
# If running manually
python -m pymol_mcp.server
```

You should see:
```
INFO - Starting PyMOL MCP server (connecting to localhost:9877)
INFO - Successfully connected to PyMOL plugin
```

### Test Connection from Client

In your MCP client (e.g., Claude Desktop), try:

```
Can you ping PyMOL?
```

Expected response:
```
✓ Connected to PyMOL (version: X.X.X)
```

### Test a Command

```
Load PDB structure 1ABC into PyMOL
```

Expected response:
```
✓ Loaded structure: 1ABC
```

## Troubleshooting

### MCP Server Won't Start

**Problem**: Client shows "Failed to start MCP server"

**Solutions**:
1. Verify Python is in PATH:
   ```bash
   which python
   python --version
   ```
2. Test manual start:
   ```bash
   python -m pymol_mcp.server
   ```
3. Check for error messages in client logs

### Connection Refused

**Problem**: "Not connected to PyMOL. Is the plugin running?"

**Solutions**:
1. Verify PyMOL is running
2. Check plugin is started: `Plugin` → `agentic-pymol plugin` → `Server Status`
3. Verify port matches configuration:
   ```bash
   lsof -i :9877
   ```
4. Test direct connection:
   ```bash
   telnet localhost 9877
   ```

### Tools Not Appearing

**Problem**: MCP tools don't show up in client

**Solutions**:
1. Restart the MCP client
2. Check client logs for MCP server errors
3. Verify MCP server is running:
   ```bash
   ps aux | grep pymol_mcp
   ```
4. Test server manually:
   ```bash
   python -m pymol_mcp.server
   ```

### Permission Errors

**Problem**: "Permission denied" when starting server

**Solutions**:
1. Check file permissions:
   ```bash
   ls -la $(which python)
   ```
2. Use absolute path to Python:
   ```json
   {
     "command": "/usr/local/bin/python3",
     "args": ["-m", "pymol_mcp.server"]
   }
   ```

### Virtual Environment Issues

**Problem**: Module not found errors

**Solutions**:
1. Activate virtual environment first
2. Use venv Python in config:
   ```json
   {
     "command": "/path/to/venv/bin/python",
     "args": ["-m", "pymol_mcp.server"]
   }
   ```
3. Install package in venv:
   ```bash
   source venv/bin/activate
   pip install -e .
   ```

## Advanced Configuration

### Multiple PyMOL Instances

To connect to different PyMOL instances on different ports:

```json
{
  "mcpServers": {
    "pymol-1": {
      "command": "python",
      "args": ["-m", "pymol_mcp.server"],
      "env": {
        "PYMOL_PORT": "9877"
      }
    },
    "pymol-2": {
      "command": "python",
      "args": ["-m", "pymol_mcp.server"],
      "env": {
        "PYMOL_PORT": "9878"
      }
    }
  }
}
```

### Remote PyMOL

To connect to PyMOL on a remote machine:

```json
{
  "mcpServers": {
    "pymol": {
      "command": "python",
      "args": ["-m", "pymol_mcp.server"],
      "env": {
        "PYMOL_HOST": "192.168.1.100",
        "PYMOL_PORT": "9877"
      }
    }
  }
}
```

**Note**: Ensure the remote PyMOL plugin is configured to accept external connections.

### Debug Mode

For troubleshooting, enable debug logging:

```json
{
  "mcpServers": {
    "pymol": {
      "command": "python",
      "args": ["-m", "pymol_mcp.server"],
      "env": {
        "PYMOL_LOG_LEVEL": "DEBUG"
      }
    }
  }
}
```

## Example Workflows

### Claude Desktop Workflow

1. **Start PyMOL**
   ```bash
   pymol
   ```

2. **Enable Plugin**
   - `Plugin` → `agentic-pymol plugin` → `Control Panel` → **Start Server**

3. **Open Claude Desktop**
   - MCP server starts automatically

4. **Use PyMOL Tools**
   ```
   Load PDB 1ABC and color chain A red
   ```

### Cline Workflow

1. Start PyMOL and enable plugin
2. Open VS Code with Cline extension
3. Start a new Cline session
4. Use PyMOL tools in your conversation

### Programmatic Usage

```python
from pymol_mcp import get_client, tools

# Connect to PyMOL
client = get_client()

# Use tools directly
tools.load_structure("1ABC")
tools.color_selection("red", "chain A")
tools.render_image("/tmp/protein.png")
```

## Support

For configuration issues:

1. Check client-specific documentation
2. Review server logs
3. Test manual server start
4. Verify PyMOL plugin is running
5. Open an issue with:
   - Client name and version
   - Configuration file contents
   - Error messages
   - Server logs
