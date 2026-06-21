import os
from pathlib import Path

# Safe .env loader — handles long JWT values without breaking on shell metacharacters
def _load_env(path=".env"):
    for line in Path(path).read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        os.environ.setdefault(key.strip(), val.strip())

_load_env()

from uagents_core.utils.registration import (
    register_chat_agent,
    RegistrationRequestCredentials,
)

api_key = os.environ.get("AGENTVERSE_API_KEY", "")
seed = os.environ.get("PYMOL_AGENT_SEED", "")
ngrok_url = os.environ.get("NGROK_URL", "").rstrip("/")

if not api_key:
    raise SystemExit("Missing AGENTVERSE_API_KEY in .env")
if not seed:
    raise SystemExit("Missing PYMOL_AGENT_SEED in .env")
if not ngrok_url:
    raise SystemExit("Missing NGROK_URL in .env — start ngrok first")

endpoint = f"{ngrok_url}/submit"
print(f"Registering PyMOLS at {endpoint} ...")

register_chat_agent(
    "PyMOLS",
    endpoint,
    active=True,
    credentials=RegistrationRequestCredentials(
        agentverse_api_key=api_key,
        agent_seed_phrase=seed,
    ),
)
print("Registration done")
