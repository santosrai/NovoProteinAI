# NovoProteinAI

A tool that uses PyMOL as typed tools to LLM agents like Claude Desktop, Cline, and Devin using MCP and pymol plugin

## Architecture

```
Claude/Devin (MCP client)
    ↕ stdio
FastMCP Server (pymol_mcp/)
    ↕ TCP (localhost:9877, JSON-RPC 2.0)
PyMOL Plugin (pymol_plugin/)
    ↕ PyMOL API
PyMOL Session
```

The bridge consists of two components:

1. **PyMOL Plugin** - TCP server running inside PyMOL that executes commands
2. **MCP Server** - FastMCP server that exposes PyMOL functionality as MCP tools

## Features

- 🔌 **5 Core Tools**: Load structures, select atoms, color, render images, health check
- 🔄 **Auto-reconnect**: Exponential backoff retry logic
- ⚙️ **Configurable**: Environment variables or YAML config file
- 🛡️ **Error Handling**: Comprehensive error handling and logging
- 📡 **JSON-RPC 2.0**: Length-prefixed wire protocol over TCP

## Installation

### 1. Install MCP Server

```bash
cd NovoProteinAI
pip install -e .
```

### 2. Install PyMOL Plugin

See [PLUGIN_INSTALL.md](PLUGIN_INSTALL.md) for detailed instructions.

**Quick method:**
1. Open PyMOL
2. Go to `Plugin` → `Plugin Manager`
3. Click `Install New Plugin` → `Choose file...`
4. Select `pymol_plugin/__init__.py`
5. Click `OK` to install

### 3. Configure MCP Client

See [MCP_CONFIG.md](MCP_CONFIG.md) for client-specific configuration.

**For Claude Desktop**, add to `~/Library/Application Support/Claude/claude_desktop_config.json`:

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

## Usage

### 1. Start PyMOL Plugin

1. Open PyMOL
2. Go to `Plugin` → `agentic-pymol plugin` → `Control Panel`
3. Click **Start Server** and watch the live status + activity log

### 2. Use from LLM Agent

The MCP server exposes 5 tools:

#### `load_structure`
Load a molecular structure from file or PDB ID.
```python
load_structure(source="/path/to/protein.pdb")
load_structure(source="1ABC", object_name="my_protein")
```

#### `select_atoms`
Create a named selection of atoms.
```python
select_atoms(selection_name="active_site", selection_expr="resi 100-150")
select_atoms(selection_name="backbone", selection_expr="name CA+C+N+O")
```

#### `color_selection`
Apply color to a selection.
```python
color_selection(color="red", selection="chain A")
color_selection(color="blue")  # colors all
```

#### `render_image`
Save an image of the current view.
```python
render_image(output_path="/tmp/protein.png", width=1920, height=1080)
render_image(output_path="/tmp/hq.png", ray_trace=True)
```

#### `ping_pymol`
Check connection and get PyMOL version.
```python
ping_pymol()
```

## Research Agent (Fetch.ai / Agentverse)

`src/research_agent.py` is a Fetch.ai uAgent that turns a plain-English
vaccine/therapeutic goal into a structured target result sourced from public
biology databases (RCSB PDB + PubMed). Its JSON output matches the inputs of
`render_image()` in `visualize.py`.

### Output contract

```json
{
  "target_name": "SARS-CoV-2 spike receptor-binding domain",
  "pdb_id": "6VXX",
  "chain": "A",
  "epitope_residues": [417, 484, 501],
  "binder_pdb_ids": ["7K8M"],
  "explanation": "Plain-English summary a non-biologist can follow.",
  "citations": [{"title": "...", "pmid": "...", "url": "https://pubmed.ncbi.nlm.nih.gov/..."}]
}
```

### Run it

```bash
pip install -r requirements.txt
export AGENT_SEED="some-fixed-phrase"     # required: stable agent address
export ASI_ONE_API_KEY="..."              # optional: falls back to keyword parsing
python src/research_agent.py
```

### Register on Agentverse

1. Run the agent — it prints an Agentverse Inspector/mailbox link.
2. Sign in at [agentverse.ai](https://agentverse.ai) and connect the mailbox so
   the agent is reachable without a public IP.
3. `publish_manifest=True` advertises chat capability, making it discoverable
   from [ASI:One](https://asi1.ai).
4. Test by messaging the agent: `build a vaccine for COVID`.

### Environment variables

- `AGENT_SEED` — fixed seed phrase for a stable agent address (required to run).
- `ASI_ONE_API_KEY` — ASI:One key for goal parsing + explanation drafting (optional).

> Note: `epitope_residues` is currently returned empty (IEDB lookup is a planned
> follow-up).

## Configuration

### Environment Variables

- `PYMOL_HOST` - PyMOL plugin host (default: `localhost`)
- `PYMOL_PORT` - PyMOL plugin port (default: `9877`)
- `PYMOL_TIMEOUT` - Request timeout in seconds (default: `30.0`)
- `PYMOL_RECONNECT_ATTEMPTS` - Number of reconnection attempts (default: `3`)
- `PYMOL_RECONNECT_DELAY` - Initial reconnection delay in seconds (default: `1.0`)
- `PYMOL_LOG_LEVEL` - Logging level (default: `INFO`)

### Configuration File

Create `config.yaml`:

```yaml
host: localhost
port: 9877
timeout: 30.0
reconnect_attempts: 3
reconnect_delay: 1.0
log_level: INFO
```

Run with config file:
```bash
python -m pymol_mcp.server --config config.yaml
```

## Development

### Project Structure

```
NovoProteinAI/
├── pymol_plugin/
│   └── __init__.py          # PyMOL plugin (TCP server)
├── pymol_mcp/
│   ├── __init__.py
│   ├── server.py            # FastMCP server entry point
│   ├── client.py            # TCP client for PyMOL
│   ├── config.py            # Configuration management
│   └── tools.py             # MCP tool definitions
├── tests/
│   ├── test_protocol.py
│   ├── test_client.py
│   └── test_tools.py
├── src/                    # Chat interface
├── requirements.txt
├── pyproject.toml
└── README.md
```

### Running Tests

```bash
pip install -e ".[dev]"
pytest tests/
```

### Manual Testing

```bash
# Terminal 1: Start PyMOL and enable plugin
pymol
# In PyMOL: Plugin → agentic-pymol plugin → Control Panel → Start Server

# Terminal 2: Test MCP server
python -m pymol_mcp.server
```

## Wire Protocol

The bridge uses **JSON-RPC 2.0** over TCP with length-prefixed messages:

```
[4-byte big-endian length][JSON payload]
```

Example request:
```json
{
  "jsonrpc": "2.0",
  "method": "load_structure",
  "params": {"source": "1ABC"},
  "id": 1
}
```

Example response:
```json
{
  "jsonrpc": "2.0",
  "result": {"message": "Loaded structure: 1ABC", "object_name": "1ABC"},
  "id": 1
}
```

## Troubleshooting

### Connection Refused
- Ensure PyMOL is running
- Verify plugin is started: `Plugin` → `agentic-pymol plugin` → `Server Status`
- Check port is not in use: `lsof -i :9877`

### Plugin Not Loading
- Check PyMOL console for errors
- Verify Python version compatibility (≥3.8)
- Try reinstalling plugin

### MCP Server Not Responding
- Check logs for connection errors
- Verify configuration (host/port)
- Test connection: `telnet localhost 9877`

## License

MIT

## Contributing

Contributions welcome! Please open an issue or PR.
