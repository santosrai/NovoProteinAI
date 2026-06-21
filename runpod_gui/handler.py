"""RunPod Serverless handler: an interactive PyMOL GUI served over noVNC.

The Serverless-to-Interactive-Session pattern
---------------------------------------------
A normal serverless worker runs a task and dies. To get a *clickable* link that
opens a live PyMOL GUI in the user's browser, we hijack the worker:

  1. Start a virtual X display (Xvfb) + a tiny window manager (fluxbox).
  2. Launch PyMOL (GUI mode) preloaded with the requested PDB and styling.
  3. Start x11vnc (password-protected) on that display.
  4. Bridge VNC -> HTML5 via websockify/noVNC on port 8080.
  5. `yield` the public RunPod proxy URL back to the caller immediately.
  6. Enter a `while True` loop so the worker (and the GUI) stays alive until
     the agent cancels the job (or the endpoint idle/execution timeout fires).

The caller (src/runpod_gui.py) reads the first streamed chunk to get the URL,
so streaming MUST be enabled on the endpoint (return_aggregate_stream=True).

Env (injected by RunPod / the endpoint template):
  RUNPOD_POD_ID   - unique worker id, used to build the proxy URL
  RUNPOD_GUI_PORT - HTTP port exposed in the template (default 8080)
"""

import os
import secrets
import subprocess
import time

DISPLAY = ":0"
SCREEN = "1280x800x24"
VNC_PORT = 5900


def _sh(cmd):
    """Launch a background process, inheriting the environment (incl. DISPLAY)."""
    return subprocess.Popen(cmd, env=os.environ.copy())


BOOT_SCRIPT = "/app/cloud_boot.py"


def _write_boot_script(pdb_id, chain="", epitope="", relay_url="", token="",
                       path=BOOT_SCRIPT):
    """Write a PyMOL startup script: load + style the target, then (optionally)
    dial out to the relay so the agent can drive this same live session.

    Styling mirrors the static renderer in research_agent.visualize_target:
    cartoon, cyan/spectrum target, red epitope.
    """
    pdb_id = (pdb_id or "1crn").strip()
    lines = [
        "import sys",
        "sys.path.insert(0, '/app')",
        "from pymol import cmd",
        f"cmd.fetch({pdb_id!r}, async_=0)",
        "cmd.hide('everything')",
        "cmd.show('cartoon')",
    ]

    if chain:
        lines.append(f"cmd.color('cyan', 'chain {chain}')")
    else:
        lines.append("cmd.spectrum()")

    if epitope:
        # epitope is a '+'-joined residue list (e.g. "12+15+19")
        sel = f"resi {epitope}"
        if chain:
            sel += f" and chain {chain}"
        lines.append(f"cmd.select('epitope', {sel!r})")
        lines.append("cmd.color('red', 'epitope')")

    lines.append("cmd.orient()")

    # Agent control: connect the plugin out to the public relay under `token`.
    # Best-effort — if the relay is unreachable, the noVNC GUI still works.
    if relay_url and token:
        lines += [
            "try:",
            "    import pymol_plugin",
            f"    pymol_plugin.start_relay({relay_url!r}, {token!r})",
            f"    print('Relay client started -> {relay_url}')",
            "except Exception as _e:",
            "    print('Relay start failed:', _e)",
        ]

    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")
    return path


def start_gui_server(pdb_id, chain="", epitope="", vnc_password="",
                     relay_url="", token=""):
    """Boot the full display -> PyMOL -> VNC -> noVNC stack in the background."""
    # 1. Virtual X11 display.
    _sh(["Xvfb", DISPLAY, "-screen", "0", SCREEN])
    os.environ["DISPLAY"] = DISPLAY
    time.sleep(2)  # let Xvfb come up before clients connect

    # 2. Minimal window manager so PyMOL's Qt window is managed/visible.
    _sh(["fluxbox"])

    # 3. PyMOL GUI, preloaded with the target + styling (+ optional relay).
    #    `-qr` runs the python boot script while keeping the GUI open.
    _write_boot_script(pdb_id, chain, epitope, relay_url, token)
    _sh(["pymol", "-qr", BOOT_SCRIPT])

    # 4. x11vnc, password-protected. Write the password to a passwd file.
    vnc_args = ["x11vnc", "-display", DISPLAY, "-listen", "localhost",
                "-xkb", "-forever", "-shared", "-rfbport", str(VNC_PORT)]
    if vnc_password:
        pw_file = "/tmp/vncpass"
        subprocess.run(["x11vnc", "-storepasswd", vnc_password, pw_file], check=False)
        vnc_args += ["-rfbauth", pw_file]
    else:
        vnc_args += ["-nopw"]
    _sh(vnc_args)

    # 5. noVNC / websockify bridge -> HTTP port.
    http_port = os.environ.get("RUNPOD_GUI_PORT", "8080")
    _sh(["websockify", "--web", "/usr/share/novnc", http_port,
         f"localhost:{VNC_PORT}"])


def handler(job):
    job_input = job.get("input", {}) or {}
    pdb_id = job_input.get("pdb_id", "1crn")
    chain = str(job_input.get("chain", "") or "")
    epitope = str(job_input.get("epitope", "") or "")
    # Optional: agent control. If both are present the cloud PyMOL dials out to
    # the relay under `token` so the agent's relay tools can drive this session.
    relay_url = str(job_input.get("relay_url", "") or "")
    token = str(job_input.get("token", "") or "")

    worker_id = os.environ.get("RUNPOD_POD_ID", "unknown")
    http_port = os.environ.get("RUNPOD_GUI_PORT", "8080")

    # One-time VNC password so the open desktop isn't reachable by URL alone.
    vnc_password = secrets.token_urlsafe(9)

    start_gui_server(pdb_id, chain, epitope, vnc_password, relay_url, token)

    # Give the background services a few seconds to boot.
    time.sleep(5)

    # Public RunPod proxy URL mapping to the internal HTTP port. The password is
    # passed via the noVNC query param so the link works on first click.
    base = f"https://{worker_id}-{http_port}.proxy.runpod.net/vnc.html"
    gui_url = f"{base}?autoconnect=true&password={vnc_password}"

    # Stream the URL back immediately, keeping the job open.
    yield {
        "status": "GUI Ready",
        "interactive_link": gui_url,
        "pdb_id": pdb_id,
        "password": vnc_password,
    }

    # Prevent the serverless function from exiting. The agent cancels the job
    # (or the endpoint idle/execution timeout fires) to stop billing.
    while True:
        time.sleep(60)


if __name__ == "__main__":
    import runpod

    runpod.serverless.start({
        "handler": handler,
        "return_aggregate_stream": True,
    })
