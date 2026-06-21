# Interactive PyMOL GUI on RunPod (Serverless + noVNC)

This is the **opt-in interactive cloud GUI** mode for NovoProteinAI. Instead of
requiring the user to install PyMOL locally (the relay path), the agent boots a
live PyMOL GUI on a RunPod Serverless worker, serves it over noVNC, and returns
a clickable browser link.

It is **additive**: the existing relay/local-PyMOL flow is unchanged. This mode
activates only when `RUNPOD_API_KEY` and `RUNPOD_ENDPOINT_ID` are set.

## How it works (Serverless-to-Interactive-Session pattern)

1. Agent tool `launch_interactive_gui` POSTs to the endpoint `/run`.
2. `handler.py` starts `Xvfb` -> `fluxbox` -> `pymol` (preloaded with the PDB)
   -> `x11vnc` (password-protected) -> `websockify`/noVNC on port 8080.
3. The handler `yield`s the proxy URL, then enters `while True` to stay alive.
4. The agent reads the first streamed chunk, gets the URL, and shares the link.
5. On "done", `close_interactive_gui` (or the chat handler) cancels the job.

## Agent control (optional)

By default the cloud session is **launch-only**: the agent preloads the
structure and you interact in the browser. To also let the **agent** drive the
same live session (load/color/select/render), the cloud PyMOL dials out to your
public relay:

- The image bakes in `pymol_plugin/`. The boot script calls
  `pymol_plugin.start_relay(relay_url, token)` so the cloud PyMOL connects to
  the relay as a normal plugin client.
- Set **`PUBLIC_RELAY_URL`** in the agent's env to your deployed relay's
  WebSocket URL, e.g. `wss://your-app.up.railway.app/plugin`. The agent passes
  this plus the session token to RunPod at launch.
- The agent's existing relay PyMOL tools then route to that token — i.e. to the
  cloud container — so the agent and your mouse share one session.

Requirements/caveats:
- The relay (this app, deployed e.g. on Railway) must be **publicly reachable**
  from RunPod. Localhost relays won't work for the cloud worker.
- RunPod Serverless only proxies HTTP, so we use the relay's **outbound**
  WebSocket (the container dials out) rather than an inbound TCP connection.
- If `PUBLIC_RELAY_URL` is unset or the relay is unreachable, it silently falls
  back to launch-only — the noVNC GUI still works.

## Build & push the image

Build from the **repo root** (the image bakes in `pymol_plugin/` for agent
control, so it must be in the build context):

```bash
docker buildx build --platform linux/amd64 \
  -f runpod_gui/Dockerfile \
  -t <registry>/novoprotein-pymol-gui:latest \
  --push .
```

### Local smoke test

```bash
# Run the GUI stack directly (bypasses the serverless handler loop):
docker run --rm -p 8080:8080 --entrypoint bash <registry>/novoprotein-pymol-gui:latest \
  -c "Xvfb :0 -screen 0 1280x800x24 & sleep 2; DISPLAY=:0 fluxbox & \
      DISPLAY=:0 pymol -d 'fetch 1crn, async=0; show cartoon; spectrum' & \
      DISPLAY=:0 x11vnc -display :0 -nopw -forever -rfbport 5900 & \
      websockify --web /usr/share/novnc 8080 localhost:5900"
# Then open http://localhost:8080/vnc.html
```

## Create the Serverless endpoint

1. RunPod Dashboard -> Serverless -> New Endpoint from the pushed image.
2. **Expose HTTP Ports: add `8080`.** (Without this the proxy URL 404s.)
3. Set **Execution Timeout** high (sessions are long-lived) and **Idle Timeout**
   low as a billing backstop. Min workers = 0 (scale to zero when idle).
4. Copy the **Endpoint ID** and your **API key**.

## Configure the agent (Railway env / .env)

```
RUNPOD_API_KEY=...
RUNPOD_ENDPOINT_ID=...
RUNPOD_GUI_PORT=8080          # must match the exposed port
RUNPOD_GUI_POLL_TIMEOUT=90
```

## Security

`handler.py` generates a one-time VNC password per launch and embeds it in the
returned `vnc.html?password=...` link, so the open desktop isn't reachable by
the proxy URL alone. Treat the link as a secret.

## Notes / limits

- CPU-only software rendering (Mesa) is sufficient for interactive viewing; no
  GPU is needed. Switch the base image to CUDA only for GPU ray tracing.
- Launch-only control: the agent preloads the structure/styling, then the user
  interacts directly. The agent does not drive the cloud session after launch.
- Always rely on the idle/execution timeout as a billing safety net in addition
  to the `/cancel` triggered on "done".
