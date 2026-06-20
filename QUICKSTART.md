# Quick Start Guide

Get the PyMOL MCP Bridge running in 5 minutes.

## 1. Install Dependencies

```bash
cd NovoProteinAI
pip install -e .
```

## 2. Install PyMOL Plugin

**Option A: Plugin Manager (Recommended)**
1. Open PyMOL
2. `Plugin` → `Plugin Manager`
3. `Install New Plugin` → Choose `pymol_plugin/__init__.py`
4. Restart PyMOL

**Option B: Manual**
```bash
# macOS
cp pymol_plugin/__init__.py ~/Library/Application\ Support/PyMOL/startup/pymol_mcp_plugin.py

# Linux
cp pymol_plugin/__init__.py ~/.pymol/startup/pymol_mcp_plugin.py
```

## 3. Start PyMOL Plugin

1. Open PyMOL
2. `Plugin` → `agentic-pymol plugin` → `Control Panel`
3. Click **Start Server** — the status turns green and the activity log goes live

The panel shows: `Status: Running`, `Port: 9877`, `Connected clients: 0`

## 4. Configure MCP Client

### Claude Desktop

Edit `~/Library/Application Support/Claude/claude_desktop_config.json`:

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

Restart Claude Desktop.

### Other Clients

See [MCP_CONFIG.md](MCP_CONFIG.md) for Cline, Devin, etc.

## 5. Test It!

In Claude Desktop (or your MCP client):

```
Can you ping PyMOL?
```

Expected: `✓ Connected to PyMOL (version: X.X.X)`

```
Load PDB structure 1ABC and color it red
```

Expected: Structure loads in PyMOL and turns red!

## Available Tools

1. **`load_structure`** - Load PDB files or fetch from PDB database
2. **`select_atoms`** - Create named selections with PyMOL syntax
3. **`color_selection`** - Apply colors to selections
4. **`render_image`** - Save PNG images (with optional ray tracing)
5. **`ping_pymol`** - Check connection status

## Example Workflows

### Load and Visualize
```
Load PDB 1ABC, select chain A, color it blue, and save an image to /tmp/protein.png
```

### Compare Structures
```
Load 1ABC as protein1 and 2XYZ as protein2, color protein1 red and protein2 blue
```

### High-Quality Rendering
```
Load 1ABC, zoom to chain A, and render a ray-traced image at 1920x1080 to /tmp/hq.png
```

## Troubleshooting

### "Not connected to PyMOL"
- Ensure PyMOL is running
- Check plugin is started: `Plugin` → `agentic-pymol plugin` → `Server Status`
- Verify port: `lsof -i :9877`

### Plugin menu not appearing
- Restart PyMOL after installation
- Check PyMOL console for errors

### MCP server won't start
- Test manually: `python -m pymol_mcp.server`
- Check Python path in config
- Verify installation: `pip list | grep fastmcp`

## Next Steps

- Read [README.md](README.md) for full documentation
- See [PLUGIN_INSTALL.md](PLUGIN_INSTALL.md) for detailed plugin setup
- Check [MCP_CONFIG.md](MCP_CONFIG.md) for advanced configuration
- Run tests: `pytest tests/`
- Try integration test: `python tests/integration_test.py`

## Support

Open an issue on GitHub with:
- PyMOL version
- Python version
- Error messages
- Steps to reproduce
