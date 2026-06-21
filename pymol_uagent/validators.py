import os
import re

SAFE_RENDER_DIR = os.path.expanduser("~/NovoProteinAI/renders")

PDB_ID_RE = re.compile(r"^[A-Za-z0-9]{4}$")

VALID_COLORS = {
    "red", "blue", "green", "yellow", "cyan", "magenta",
    "orange", "white", "black", "gray", "pink", "purple",
    "salmon", "slate", "teal", "violet", "wheat",
}

PROJECT_ROOT = os.path.realpath(
    os.path.join(os.path.dirname(__file__), "..")
)


def validate_source(source: str) -> str:
    """Allow PDB IDs or file paths inside project root only."""
    if PDB_ID_RE.match(source):
        return source.upper()
    abs_path = os.path.realpath(source)
    if abs_path.startswith(PROJECT_ROOT):
        return abs_path
    raise ValueError(f"Unsafe source: {source!r}. Use a 4-char PDB ID or project-relative path.")


def validate_output_path(path: str) -> str:
    """Force output into SAFE_RENDER_DIR, reject path traversal."""
    os.makedirs(SAFE_RENDER_DIR, exist_ok=True)
    filename = os.path.basename(path)
    if not filename.endswith(".png"):
        raise ValueError("output_path must end in .png")
    if not filename or filename == ".png":
        raise ValueError("output_path filename cannot be empty")
    safe = os.path.join(SAFE_RENDER_DIR, filename)
    # double-check no traversal survived
    if not os.path.realpath(safe).startswith(os.path.realpath(SAFE_RENDER_DIR)):
        raise ValueError("Path traversal detected in output_path")
    return safe


def validate_color(color: str) -> str:
    """Restrict to known-safe PyMOL color names."""
    c = color.lower().strip()
    if c not in VALID_COLORS:
        raise ValueError(f"Color {color!r} not allowed. Choose from: {sorted(VALID_COLORS)}")
    return c


def validate_dimensions(width: int, height: int) -> tuple[int, int]:
    """Clamp render dimensions to safe bounds."""
    return min(max(width, 100), 3840), min(max(height, 100), 2160)
