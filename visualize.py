"""
PyMOL visualization layer for NovoProteinAI.

This module is intentionally "dumb": it does NOT decide what to show.
The Claude-powered pipeline figures out the target (PDB ID), which residues
are the epitope, and any known binders, then calls into here to render.

Two entry points:
  - render_image():    headless, saves a PNG. Use this in the pipeline / for
                       Devin automation / to embed in the web UI. Works anywhere.
  - open_interactive(): opens the real PyMOL window for manual exploration.
                       Shells out to the `pymol` launcher so the GUI starts on
                       the macOS main thread (avoids the NSWindow crash you get
                       from finish_launching() inside a plain python process).

Run the demo:
    python visualize.py            # renders target.png
    python visualize.py --window   # opens the interactive PyMOL window
"""

import subprocess
import sys


def _scene_commands(pdb_id, epitope_residues=None, chain=None, binder_pdb_id=None):
    """
    Build the shared list of PyMOL command-language strings that define the scene.

    Both the headless PNG path and the interactive .pml path use this, so the
    visualization stays identical between them (single source of truth).

    Returns a list of strings, each a line of PyMOL command language.
    """
    # If a chain is given, show only that chain so the trimer's other copies
    # don't clutter the view (and don't get pulled in by the epitope zoom).
    target_sel = f"target and chain {chain}" if chain else "target"

    lines = [
        # async=0 forces the fetch to finish before the next command runs.
        f"fetch {pdb_id}, name=target, async=0",
        "hide everything, target",
        f"show cartoon, {target_sel}",
        f"color cyan, {target_sel}",
    ]

    if epitope_residues:
        resi_str = "+".join(str(r) for r in epitope_residues)
        sel = f"target and resi {resi_str}"
        if chain:
            sel += f" and chain {chain}"
        lines += [
            f"select epitope, {sel}",
            "show sticks, epitope",
            "color red, epitope",
            "zoom epitope, 8",
        ]
    else:
        lines.append("zoom target")

    if binder_pdb_id:
        lines += [
            f"fetch {binder_pdb_id}, name=binder, async=0",
            "hide everything, binder",
            "show cartoon, binder",
            "color yellow, binder",
        ]

    # Clean default look for the demo.
    lines += [
        "bg_color white",
        "set ray_opaque_background, 0",
    ]
    return lines


def render_image(
    pdb_id,
    epitope_residues=None,
    chain=None,
    binder_pdb_id=None,
    out_path="target.png",
    width=1200,
    height=900,
):
    """
    Headless render of the scene to a PNG. Reliable everywhere (no display
    needed), so this is what the pipeline / Devin should call.

    Returns the path to the written image.
    """
    # Import here so the interactive path doesn't pull PyMOL into-process.
    import pymol
    from pymol import cmd

    # -qc = quiet, no GUI. Safe to launch headless on any thread.
    pymol.finish_launching(["pymol", "-qc"])
    cmd.reinitialize()

    for line in _scene_commands(pdb_id, epitope_residues, chain, binder_pdb_id):
        cmd.do(line)

    # ray = high-quality offline render; then write the PNG.
    cmd.ray(width, height)
    cmd.png(out_path, dpi=150)
    return out_path


def open_interactive(
    pdb_id,
    epitope_residues=None,
    chain=None,
    binder_pdb_id=None,
    pml_path="scene.pml",
):
    """
    Open the real PyMOL window for manual exploration.

    Writes the scene to a .pml script and launches it via the `pymol` binary,
    which sets up the GUI on the macOS main thread. This avoids the NSException
    crash you get from calling finish_launching() with a GUI inside a plain
    `python script.py` process on macOS.
    """
    with open(pml_path, "w") as f:
        f.write("\n".join(_scene_commands(pdb_id, epitope_residues, chain, binder_pdb_id)))
        f.write("\n")

    # `pymol scene.pml` opens the window and runs the script in it.
    subprocess.run(["pymol", pml_path])
    return pml_path


if __name__ == "__main__":
    # Demo: COVID-19 spike protein with three RBD escape-mutation residues.
    demo = dict(pdb_id="6VXX", epitope_residues=[417, 484, 501], chain="A")

    if "--window" in sys.argv:
        open_interactive(**demo)
    else:
        path = render_image(**demo)
        print(f"Wrote {path}")
