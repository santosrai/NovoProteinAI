# PyMOLS — PyMOL AI Agent

An AI agent that controls PyMOL molecular visualization software through natural language. Load protein structures, color chains, and render images by chatting with the agent.

## What it does

PyMOLS bridges natural language commands to a live PyMOL session running on the operator's machine. Send a message, get a PyMOL action executed in real time.

## Supported Commands

| Command | Example |
|---|---|
| Load a protein structure | `load 1ABC` |
| Load from PDB ID | `load 6PYL` |
| Color a chain | `color red chain A` |
| Color all atoms | `color blue` |
| Render screenshot | `render` |
| Check connection | `ping` |

## Example Usage

```
User: load 1ABC
Agent: ✓ Loaded structure: 1ABC

User: color red chain A
Agent: ✓ Colored chain A with red

User: render
Agent: ✓ Rendered image saved

User: ping
Agent: ✓ Connected to PyMOL (version: 3.1.0)
```

## Architecture

```
ASI:One / Agentverse
    ↓ ChatMessage
PyMOLS uAgent (this agent)
    ↓ MCP protocol (stdio)
PyMOL MCP Bridge (FastMCP)
    ↓ TCP localhost:9877
PyMOL Plugin
    ↓ cmd.* API
PyMOL Session (live 3D viewer)
```

## Requirements

- PyMOL open-source running locally with MCP plugin enabled
- Agent operator must have PyMOL plugin started before accepting requests

## Keywords

protein, pymol, molecular visualization, structural biology, PDB, drug discovery, protein design, bioinformatics, chemistry, 3D structure
