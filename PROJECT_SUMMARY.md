# PyMOL MCP Bridge - Project Summary

## Overview

A lightweight Model Context Protocol (MCP) bridge that exposes PyMOL molecular visualization software as typed tools to LLM agents (Claude Desktop, Cline, Devin, etc.).

## Architecture

```
┌─────────────────┐
│  LLM Agent      │  (Claude/Devin/Cline)
│  (MCP Client)   │
└────────┬────────┘
         │ stdio
         ▼
┌─────────────────┐
│  FastMCP Server │  (pymol_mcp/)
│  (Python)       │
└────────┬────────┘
         │ TCP (JSON-RPC 2.0)
         │ localhost:9877
         ▼
┌─────────────────┐
│  PyMOL Plugin   │  (pymol_plugin/)
│  (TCP Server)   │
└────────┬────────┘
         │ PyMOL API
         ▼
┌─────────────────┐
│  PyMOL Session  │
└─────────────────┘
```

## Components

### 1. PyMOL Plugin (`pymol_plugin/__init__.py`)
- **Purpose**: TCP server running inside PyMOL
- **Protocol**: Length-prefixed JSON-RPC 2.0
- **Port**: 9877 (configurable)
- **Features**:
  - Threaded server (non-blocking GUI)
  - Menu integration (Start/Stop/Status)
  - 5 command handlers
  - Comprehensive error handling

### 2. MCP Server (`pymol_mcp/`)
- **Purpose**: FastMCP server exposing PyMOL as MCP tools
- **Transport**: stdio (standard MCP)
- **Files**:
  - `server.py` - FastMCP entry point
  - `client.py` - TCP client with auto-reconnect
  - `tools.py` - 5 MCP tool definitions
  - `config.py` - Configuration management

### 3. Wire Protocol
- **Format**: JSON-RPC 2.0
- **Framing**: 4-byte big-endian length prefix + JSON payload
- **Error Codes**:
  - `-32700`: Parse error
  - `-32600`: Invalid request
  - `-32601`: Method not found
  - `-32602`: Invalid params
  - `-32000`: PyMOL execution error
  - `-32300`: Connection error

## Tools (5 Core Functions)

### 1. `load_structure`
Load molecular structures from files or PDB database.
```python
load_structure(source: str, object_name: Optional[str] = None) -> str
```

### 2. `select_atoms`
Create named selections using PyMOL syntax.
```python
select_atoms(selection_name: str, selection_expr: str) -> str
```

### 3. `color_selection`
Apply colors to selections.
```python
color_selection(color: str, selection: str = "all") -> str
```

### 4. `render_image`
Save PNG images with optional ray tracing.
```python
render_image(
    output_path: str,
    width: int = 800,
    height: int = 600,
    ray_trace: bool = False
) -> str
```

### 5. `ping_pymol`
Health check and version info.
```python
ping_pymol() -> str
```

## Configuration

### Environment Variables
- `PYMOL_HOST` - Default: `localhost`
- `PYMOL_PORT` - Default: `9877`
- `PYMOL_TIMEOUT` - Default: `30.0` seconds
- `PYMOL_RECONNECT_ATTEMPTS` - Default: `3`
- `PYMOL_RECONNECT_DELAY` - Default: `1.0` seconds
- `PYMOL_LOG_LEVEL` - Default: `INFO`

### Config File (YAML)
```yaml
host: localhost
port: 9877
timeout: 30.0
reconnect_attempts: 3
reconnect_delay: 1.0
log_level: INFO
```

## Project Structure

```
NovoProteinAI/
├── pymol_plugin/
│   └── __init__.py              # PyMOL plugin (TCP server)
├── pymol_mcp/
│   ├── __init__.py
│   ├── server.py                # FastMCP server entry point
│   ├── client.py                # TCP client with reconnection
│   ├── config.py                # Configuration management
│   └── tools.py                 # MCP tool definitions
├── tests/
│   ├── __init__.py
│   ├── test_protocol.py         # Protocol unit tests
│   ├── test_client.py           # Client unit tests
│   ├── test_tools.py            # Tools unit tests
│   └── integration_test.py      # End-to-end integration test
├── src/                         # Reserved for future chat interface
├── requirements.txt             # Python dependencies
├── pyproject.toml               # Package configuration
├── pytest.ini                   # Test configuration
├── .gitignore                   # Git ignore rules
├── .env.example                 # Example environment config
├── config.yaml.example          # Example YAML config
├── mcp_config.json              # Example MCP client config
├── README.md                    # Main documentation
├── QUICKSTART.md                # Quick start guide
├── PLUGIN_INSTALL.md            # Plugin installation guide
├── MCP_CONFIG.md                # MCP client configuration guide
└── PROJECT_SUMMARY.md           # This file
```

## Installation

```bash
# 1. Install MCP server
cd NovoProteinAI
pip install -e .

# 2. Install PyMOL plugin
# Open PyMOL → Plugin → Plugin Manager → Install New Plugin
# Select: pymol_plugin/__init__.py

# 3. Configure MCP client (e.g., Claude Desktop)
# Edit: ~/Library/Application Support/Claude/claude_desktop_config.json
{
  "mcpServers": {
    "pymol": {
      "command": "python",
      "args": ["-m", "pymol_mcp.server"]
    }
  }
}
```

## Usage

### 1. Start PyMOL Plugin
```
PyMOL → Plugin → agentic-pymol plugin → Control Panel → Start Server
```

### 2. Use from LLM Agent
```
Load PDB 1ABC and color chain A red
```

### 3. Programmatic Usage
```python
from pymol_mcp import tools

tools.load_structure("1ABC")
tools.color_selection("red", "chain A")
tools.render_image("/tmp/protein.png")
```

## Testing

### Unit Tests
```bash
pytest tests/
```

### Integration Test
```bash
# Requires PyMOL running with plugin started
python tests/integration_test.py
```

## Key Features

✅ **Minimal Dependencies** - Only FastMCP and PyYAML  
✅ **Auto-Reconnect** - Exponential backoff retry logic  
✅ **Type-Safe** - Fully typed Python with docstrings  
✅ **Error Handling** - Comprehensive error codes and messages  
✅ **Configurable** - Environment vars or YAML config  
✅ **Well-Documented** - Multiple guides and examples  
✅ **Tested** - Unit tests and integration test  
✅ **Extensible** - Easy to add new tools  

## Future Enhancements (Out of Scope - Phase 2)

- Chat interface in `src/` directory
- Streaming/async operations
- Multiple concurrent PyMOL sessions
- Advanced PyMOL commands (RMSD, alignments, etc.)
- Web-based visualization
- Jupyter notebook integration

## Dependencies

### Runtime
- `fastmcp>=0.1.0` - MCP server framework
- `pyyaml>=6.0` - Configuration file support
- `pymol` - PyMOL (for plugin only)

### Development
- `pytest>=7.0` - Testing framework
- `pytest-asyncio>=0.21` - Async test support

## License

MIT

## Contributing

Contributions welcome! Areas for improvement:
- Additional PyMOL commands
- Performance optimizations
- Better error messages
- More comprehensive tests
- Documentation improvements

## Support

For issues or questions:
1. Check documentation (README, QUICKSTART, guides)
2. Run integration test to verify setup
3. Check logs for error messages
4. Open GitHub issue with details

## Credits

Built for NovoProteinAI to enable LLM agents to control PyMOL for molecular visualization and analysis.
