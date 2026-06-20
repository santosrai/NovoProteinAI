"""
Devin API client for NovoProteinAI (runtime integration).

Devin's job at runtime is CODE generation, not research (research is the
Fetch.ai agent's job). The domain helper here asks Devin to write a custom
PyMOL script for a natural-language visualization request, which we can then
run through the same machinery as visualize.py.

Auth: set your Devin API key in the environment:
    export DEVIN_API_KEY=...

Devin v1 API used here:
  POST /v1/sessions                  -> create a session (optionally structured)
  GET  /v1/sessions/{session_id}     -> poll status + structured_output
  POST /v1/sessions/{session_id}/message -> send a follow-up instruction
"""

import os
import time

import requests

BASE_URL = "https://api.devin.ai/v1"

# status_enum values Devin reports; these two mean "stop polling".
TERMINAL_STATES = {"finished", "blocked", "expired", "stopped"}


class DevinError(RuntimeError):
    """Raised when the Devin API returns an error or a session fails."""


class DevinClient:
    def __init__(self, api_key=None, base_url=BASE_URL):
        self.api_key = api_key or os.environ.get("DEVIN_API_KEY")
        if not self.api_key:
            raise DevinError("No Devin API key. Set DEVIN_API_KEY in the environment.")
        self.base_url = base_url
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            }
        )

    def _post(self, path, payload):
        resp = self.session.post(f"{self.base_url}{path}", json=payload, timeout=30)
        if not resp.ok:
            raise DevinError(f"POST {path} -> {resp.status_code}: {resp.text}")
        return resp.json()

    def _get(self, path):
        resp = self.session.get(f"{self.base_url}{path}", timeout=30)
        if not resp.ok:
            raise DevinError(f"GET {path} -> {resp.status_code}: {resp.text}")
        return resp.json()

    # --- core session API -------------------------------------------------

    def create_session(self, prompt, structured_output_schema=None, title=None, tags=None):
        """
        Start a Devin session. Returns the raw response, including session_id and url.

        Pass structured_output_schema (a JSON-schema-style dict) to make Devin
        return machine-readable results in `structured_output`.
        """
        payload = {"prompt": prompt}
        if structured_output_schema is not None:
            payload["structured_output_schema"] = structured_output_schema
        if title:
            payload["title"] = title
        if tags:
            payload["tags"] = tags
        return self._post("/sessions", payload)

    def get_session(self, session_id):
        """Fetch current session state, including status_enum and structured_output."""
        return self._get(f"/sessions/{session_id}")

    def send_message(self, session_id, message):
        """Send a follow-up instruction to a running session."""
        return self._post(f"/sessions/{session_id}/message", {"message": message})

    def wait_for_session(self, session_id, poll_interval=10, max_wait=900):
        """
        Poll a session until it reaches a terminal state or max_wait seconds elapse.

        Uses gentle backoff (capped at 30s) to avoid hammering the API. Returns the
        final session object. Raises DevinError on timeout.
        """
        waited = 0
        interval = poll_interval
        while waited < max_wait:
            data = self.get_session(session_id)
            status = data.get("status_enum")
            if status in TERMINAL_STATES:
                return data
            time.sleep(interval)
            waited += interval
            interval = min(interval * 1.5, 30)
        raise DevinError(f"Session {session_id} did not finish within {max_wait}s")

    def run_task(self, prompt, structured_output_schema=None, **kwargs):
        """
        Convenience: create a session, wait for it to finish, return the final
        session object (with structured_output populated if a schema was given).
        """
        created = self.create_session(prompt, structured_output_schema, **kwargs)
        session_id = created["session_id"]
        return self.wait_for_session(session_id)


# --- domain helper: Devin writes a custom PyMOL script ---------------------

# The structured shape we ask Devin to return for a visualization request.
PYMOL_SCRIPT_SCHEMA = {
    "type": "object",
    "properties": {
        "pml_script": {
            "type": "string",
            "description": "A complete PyMOL command-language (.pml) script.",
        },
        "explanation": {
            "type": "string",
            "description": "Plain-English description of what the script shows.",
        },
    },
    "required": ["pml_script"],
}


def generate_pymol_script(request, pdb_id, epitope_residues=None, chain=None, client=None):
    """
    Ask Devin to write a custom PyMOL .pml script for a natural-language request,
    e.g. "show the surface colored by hydrophobicity and label the epitope".

    Returns a dict: {"pml_script": ..., "explanation": ...}.

    Note: Devin sessions take minutes, so this is best for "give me a new view"
    style requests, not instant interactive rendering. For the standard epitope
    view, use visualize.render_image() directly.
    """
    client = client or DevinClient()
    prompt = (
        "Write a PyMOL command-language (.pml) script for this visualization "
        f"request: {request!r}.\n\n"
        f"The target is PDB {pdb_id}"
        + (f", chain {chain}" if chain else "")
        + (f", epitope residues {epitope_residues}" if epitope_residues else "")
        + ".\n\n"
        "The script must start by fetching the structure "
        f"(`fetch {pdb_id}, async=0`). Return only the script in `pml_script` and "
        "a one-sentence `explanation`. Do not include shell commands or prose "
        "inside the script."
    )
    result = client.run_task(
        prompt,
        structured_output_schema=PYMOL_SCRIPT_SCHEMA,
        title=f"PyMOL script: {request[:40]}",
        tags=["novoprotein", "pymol"],
    )
    return result.get("structured_output", {})


if __name__ == "__main__":
    # Smoke test: requires DEVIN_API_KEY. Kicks off a real Devin session.
    out = generate_pymol_script(
        request="show the structure as a surface, color the epitope red, and label it",
        pdb_id="6VXX",
        epitope_residues=[417, 484, 501],
        chain="A",
    )
    print(out.get("explanation", "(no explanation returned)"))
    print("---")
    print(out.get("pml_script", "(no script returned)"))
