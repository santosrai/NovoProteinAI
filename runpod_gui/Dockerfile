# Interactive PyMOL GUI over noVNC for RunPod Serverless, with optional agent
# control via the relay (the cloud PyMOL dials out to your public relay).
#
# CPU-only software rendering (Mesa) is enough for interactive viewing; no GPU
# is required. Use a CUDA base only if you later add GPU ray tracing.
#
# IMPORTANT: build from the REPO ROOT so pymol_plugin/ is in the build context:
#   docker buildx build --platform linux/amd64 \
#     -f runpod_gui/Dockerfile -t <user>/novoprotein-pymol-gui:latest --push .
FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive

# PyMOL + a virtual display + a window manager + a VNC server + noVNC bridge,
# plus the OpenGL libs PyMOL's GUI needs to render headless under Xvfb.
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3-pip \
    pymol \
    xvfb \
    fluxbox \
    x11vnc \
    novnc \
    websockify \
    libgl1-mesa-glx \
    libglu1-mesa \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY runpod_gui/handler.py /app/handler.py
# The PyMOL plugin (its PyMOLRelayClient dials out to the relay for agent
# control). Imported by the boot script handler.py writes.
COPY pymol_plugin /app/pymol_plugin

# RunPod SDK (serverless worker runtime) + the outbound WebSocket client the
# plugin's relay mode needs.
RUN pip3 install --no-cache-dir runpod websocket-client

# Exposed for documentation; the port must ALSO be added under the endpoint
# template's "Expose HTTP Ports" or the proxy URL returns 404.
ENV RUNPOD_GUI_PORT=8080
EXPOSE 8080

CMD ["python3", "handler.py"]
