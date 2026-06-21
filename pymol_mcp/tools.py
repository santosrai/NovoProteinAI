from typing import Optional
import logging
from .client import get_client

logger = logging.getLogger(__name__)


def load_structure(source: str, object_name: Optional[str] = None) -> str:
    """
    Load a molecular structure into PyMOL.
    
    Args:
        source: File path to structure file (PDB, CIF, MOL2, SDF) or PDB ID (e.g., '1ABC')
        object_name: Optional name for the loaded object. If not provided, uses filename or PDB ID
    
    Returns:
        Success message with the object name
    
    Examples:
        - load_structure("/path/to/protein.pdb")
        - load_structure("1ABC", "my_protein")
        - load_structure("/data/molecule.cif", "molecule")
    """
    client = get_client()
    
    response = client.call("load_structure", {
        "source": source,
        "object_name": object_name or ""
    })
    
    if "error" in response:
        error = response["error"]
        raise Exception(f"PyMOL error ({error['code']}): {error['message']}")
    
    result = response.get("result", {})
    return f"✓ {result.get('message', 'Structure loaded')}"


def select_atoms(selection_name: str, selection_expr: str) -> str:
    """
    Create a named selection of atoms in PyMOL.
    
    Args:
        selection_name: Name for the new selection
        selection_expr: PyMOL selection expression (e.g., 'resn ALA', 'chain A and resi 1-10')
    
    Returns:
        Message with the number of atoms selected
    
    Examples:
        - select_atoms("active_site", "resi 100-150")
        - select_atoms("backbone", "name CA+C+N+O")
        - select_atoms("chain_a", "chain A")
    """
    client = get_client()
    
    response = client.call("select_atoms", {
        "selection_name": selection_name,
        "selection_expr": selection_expr
    })
    
    if "error" in response:
        error = response["error"]
        raise Exception(f"PyMOL error ({error['code']}): {error['message']}")
    
    result = response.get("result", {})
    count = result.get("count", 0)
    return f"✓ Selected {count} atoms in '{selection_name}'"


def color_selection(color: str, selection: str = "all") -> str:
    """
    Apply a color to a selection in PyMOL.
    
    Args:
        color: Color name (e.g., 'red', 'blue', 'green', 'cyan', 'magenta', 'yellow', 'orange')
        selection: Selection to color (default: 'all')
    
    Returns:
        Confirmation message
    
    Examples:
        - color_selection("red", "chain A")
        - color_selection("blue")
        - color_selection("green", "active_site")
    """
    client = get_client()
    
    response = client.call("color_selection", {
        "color": color,
        "selection": selection
    })
    
    if "error" in response:
        error = response["error"]
        raise Exception(f"PyMOL error ({error['code']}): {error['message']}")
    
    result = response.get("result", {})
    return f"✓ {result.get('message', 'Color applied')}"


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

    Examples:
        - rotate("y", 90)
        - rotate("x", 45, "6pyj")
        - rotate("z", 180)
    """
    client = get_client()

    response = client.call("rotate", {
        "axis": axis,
        "angle": angle,
        "selection": selection
    })

    if "error" in response:
        error = response["error"]
        raise Exception(f"PyMOL error ({error['code']}): {error['message']}")

    result = response.get("result", {})
    return f"✓ {result.get('message', 'Rotation applied')}"


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
    
    Examples:
        - render_image("/tmp/protein.png")
        - render_image("/tmp/high_quality.png", 1920, 1080, ray_trace=True)
        - render_image("./output.png", 1024, 768)
    """
    client = get_client()
    
    response = client.call("render_image", {
        "output_path": output_path,
        "width": width,
        "height": height,
        "ray_trace": ray_trace
    })
    
    if "error" in response:
        error = response["error"]
        raise Exception(f"PyMOL error ({error['code']}): {error['message']}")
    
    result = response.get("result", {})
    path = result.get("path", output_path)
    quality = "ray-traced" if ray_trace else "standard"
    return f"✓ Rendered {quality} image ({width}x{height}): {path}"


def ping_pymol() -> str:
    """
    Check connection to PyMOL and get version information.
    
    Returns:
        Connection status and PyMOL version
    
    Examples:
        - ping_pymol()
    """
    client = get_client()
    
    response = client.call("ping")
    
    if "error" in response:
        error = response["error"]
        raise Exception(f"Connection error ({error['code']}): {error['message']}")
    
    result = response.get("result", {})
    version = result.get("version", "unknown")
    return f"✓ Connected to PyMOL (version: {version})"
