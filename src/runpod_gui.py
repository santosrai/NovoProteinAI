"""Agent-side client for the RunPod interactive PyMOL GUI (new mode).

This is the cloud counterpart to the relay/local-PyMOL path: instead of driving
a PyMOL the user installed locally, the agent asks a RunPod Serverless endpoint
to boot an interactive PyMOL GUI over noVNC and returns a clickable browser link
(see runpod_gui/handler.py for the worker side).

Talks to the RunPod REST API with `requests` (no extra hard dependency):
  POST {base}/run            -> start a job (returns job id)
  GET  {base}/stream/{id}    -> read streamed chunks (the handler yields the URL)
  POST {base}/cancel/{id}    -> stop the job (and billing)

All functions are best-effort and never raise, so a missing/misconfigured
RunPod setup degrades gracefully in chat instead of breaking the agent.

Env:
  RUNPOD_API_KEY          - required to enable this mode
  RUNPOD_ENDPOINT_ID      - the Serverless endpoint id
  RUNPOD_GUI_POLL_TIMEOUT - seconds to wait for the URL chunk (default 90)
"""

import os
import time
from typing import Optional

import requests

_API_BASE = "https://api.runpod.ai/v2"
_HTTP_TIMEOUT = 30


def is_enabled() -> bool:
    """True if the RunPod interactive-GUI mode is configured."""
    return bool(os.environ.get("RUNPOD_API_KEY") and os.environ.get("RUNPOD_ENDPOINT_ID"))


def _endpoint_base() -> Optional[str]:
    endpoint_id = os.environ.get("RUNPOD_ENDPOINT_ID")
    return f"{_API_BASE}/{endpoint_id}" if endpoint_id else None


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {os.environ.get('RUNPOD_API_KEY', '')}",
        "Content-Type": "application/json",
    }


def _extract_link(chunk) -> Optional[str]:
    """Pull the interactive_link out of a streamed output payload (best-effort)."""
    if isinstance(chunk, dict):
        if "interactive_link" in chunk:
            return chunk["interactive_link"]
        # RunPod wraps yielded values under "output" (and sometimes lists).
        out = chunk.get("output")
        if isinstance(out, dict) and "interactive_link" in out:
            return out["interactive_link"]
        if isinstance(out, list):
            for item in out:
                link = _extract_link(item)
                if link:
                    return link
    return None


def launch_gui(pdb_id: str, chain: str = "", epitope: str = "",
               relay_url: str = "", token: str = "") -> dict:
    """Start an interactive cloud PyMOL session and return its link + job id.

    If `relay_url` and `token` are given, the cloud PyMOL dials out to that
    relay under `token` so the agent's relay PyMOL tools can drive the same
    live session (otherwise it's a launch-only, user-driven viewer).

    Returns: {"ok": bool, "url": str | None, "job_id": str | None, "message": str}
    """
    if not is_enabled():
        return {
            "ok": False, "url": None, "job_id": None,
            "message": "Interactive cloud GUI is not configured (set RUNPOD_API_KEY and RUNPOD_ENDPOINT_ID).",
        }

    base = _endpoint_base()
    payload = {"input": {
        "pdb_id": pdb_id,
        "chain": chain or "",
        "epitope": epitope or "",
        "relay_url": relay_url or "",
        "token": token or "",
    }}

    try:
        r = requests.post(f"{base}/run", json=payload, headers=_headers(), timeout=_HTTP_TIMEOUT)
        r.raise_for_status()
        job_id = r.json().get("id")
    except Exception as exc:  # noqa: BLE001 - surface as a readable status
        return {"ok": False, "url": None, "job_id": None, "message": f"Failed to start RunPod job: {exc}"}

    if not job_id:
        return {"ok": False, "url": None, "job_id": None, "message": "RunPod did not return a job id."}

    # Poll the stream until the handler yields the URL (or we time out).
    deadline = time.time() + float(os.environ.get("RUNPOD_GUI_POLL_TIMEOUT", "90"))
    while time.time() < deadline:
        try:
            s = requests.get(f"{base}/stream/{job_id}", headers=_headers(), timeout=_HTTP_TIMEOUT)
            s.raise_for_status()
            data = s.json()
        except Exception:
            time.sleep(2)
            continue

        for chunk in data.get("stream", []) or []:
            link = _extract_link(chunk.get("output", chunk))
            if link:
                return {"ok": True, "url": link, "job_id": job_id, "message": "Interactive GUI ready."}

        if data.get("status") in ("FAILED", "CANCELLED"):
            return {"ok": False, "url": None, "job_id": job_id, "message": f"RunPod job {data.get('status')}."}

        time.sleep(2)

    # Timed out waiting for the URL: cancel so we don't leak a billed worker.
    close_gui(job_id)
    return {"ok": False, "url": None, "job_id": job_id, "message": "Timed out waiting for the GUI to boot."}


def close_gui(job_id: str) -> dict:
    """Cancel a running interactive session to stop billing. Never raises."""
    if not job_id:
        return {"ok": False, "message": "No active session to close."}
    base = _endpoint_base()
    if not base:
        return {"ok": False, "message": "RunPod endpoint not configured."}
    try:
        r = requests.post(f"{base}/cancel/{job_id}", headers=_headers(), timeout=_HTTP_TIMEOUT)
        r.raise_for_status()
        return {"ok": True, "message": f"Closed interactive session {job_id}."}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "message": f"Failed to close session {job_id}: {exc}"}
