import sys
import logging
from typing import Optional
from fastmcp import FastMCP
from .config import PyMOLConfig
from .client import get_client
from . import tools

logger = logging.getLogger(__name__)

mcp = FastMCP("PyMOL MCP Bridge")


@mcp.tool()
def load_structure(source: str, object_name: Optional[str] = None) -> str:
    """
    Load a molecular structure into PyMOL.

    Opens local structure files (including your own non-PDB CIF files) or
    fetches a structure from the PDB by ID.

    Args:
        source: A local file path or a 4-character PDB ID. Supported local
            extensions (optionally gzipped): .pdb, .ent, .cif, .mmcif, .mcif,
            .mol2, .mol, .sdf, .xyz, .pdbqt, .mae. The file must exist on the
            machine where PyMOL is running.
        object_name: Optional name for the loaded object. If not provided, uses filename or PDB ID

    Returns:
        Success message with the object name
    """
    return tools.load_structure(source, object_name)


@mcp.tool()
def select_atoms(selection_name: str, selection_expr: str) -> str:
    """
    Create a named selection of atoms in PyMOL.
    
    Args:
        selection_name: Name for the new selection
        selection_expr: PyMOL selection expression (e.g., 'resn ALA', 'chain A and resi 1-10')
    
    Returns:
        Message with the number of atoms selected
    """
    return tools.select_atoms(selection_name, selection_expr)


@mcp.tool()
def color_selection(color: str, selection: str = "all") -> str:
    """
    Apply a color to a selection in PyMOL.
    
    Args:
        color: Color name (e.g., 'red', 'blue', 'green', 'cyan', 'magenta', 'yellow', 'orange')
        selection: Selection to color (default: 'all')
    
    Returns:
        Confirmation message
    """
    return tools.color_selection(color, selection)


@mcp.tool()
def rotate(axis: str = "y", angle: float = 90, selection: str = "") -> str:
    """
    Rotate the camera view or a specific object/selection in PyMOL.

    Args:
        axis: Rotation axis, one of 'x', 'y', or 'z' (default: 'y')
        angle: Rotation angle in degrees (default: 90)
        selection: Optional object/selection to rotate. If empty, rotates the
            camera view instead of the molecule (default: '')

    Returns:
        Confirmation message
    """
    return tools.rotate(axis, angle, selection)


@mcp.tool()
def render_image(
    output_path: str,
    width: int = 800,
    height: int = 600,
    ray_trace: bool = False
) -> str:
    """
    Render and save an image of the current PyMOL view.
    
    Args:
        output_path: Path where the PNG image will be saved
        width: Image width in pixels (default: 800)
        height: Image height in pixels (default: 600)
        ray_trace: Whether to use ray tracing for high-quality rendering (default: False)
    
    Returns:
        Path to the saved image
    """
    return tools.render_image(output_path, width, height, ray_trace)


@mcp.tool()
def ping_pymol() -> str:
    """
    Check connection to PyMOL and get version information.
    
    Returns:
        Connection status and PyMOL version
    """
    return tools.ping_pymol()


def main():
    """Main entry point for the MCP server."""
    import argparse
    
    parser = argparse.ArgumentParser(description="PyMOL MCP Bridge Server")
    parser.add_argument(
        "--config",
        type=str,
        help="Path to configuration file (YAML)"
    )
    parser.add_argument(
        "--host",
        type=str,
        help="PyMOL plugin host (overrides config)"
    )
    parser.add_argument(
        "--port",
        type=int,
        help="PyMOL plugin port (overrides config)"
    )
    
    args = parser.parse_args()
    
    config = PyMOLConfig.load(args.config)
    
    if args.host:
        config.host = args.host
    if args.port:
        config.port = args.port
    
    client = get_client(config)
    
    logger.info(f"Starting PyMOL MCP server (connecting to {config.host}:{config.port})")
    
    if not client.ping():
        logger.warning("Could not connect to PyMOL plugin. Make sure PyMOL is running and the plugin is started.")
        logger.warning("The server will start anyway and attempt to connect on first request.")
    else:
        logger.info("Successfully connected to PyMOL plugin")
    
    try:
        mcp.run()
    except KeyboardInterrupt:
        logger.info("Shutting down PyMOL MCP server")
        client.disconnect()
        sys.exit(0)
    except Exception as e:
        logger.error(f"Server error: {e}")
        client.disconnect()
        sys.exit(1)


if __name__ == "__main__":
    main()
