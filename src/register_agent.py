"""
Register the NovoProteinAI agent's chat capability on Agentverse.

Reads credentials from .env:
  AGENTVERSE_KEY   - Agentverse API key (Profile -> API Keys)
  AGENT_SEED       - the SAME seed phrase the agent runs with (research_agent.py)

The endpoint must be where the running agent is reachable. 127.0.0.1 only works
from this machine; for Agentverse to reach it you need a PUBLIC url (deploy or a
tunnel like ngrok). For local-only use, prefer the mailbox flow in the inspector.
"""

import os

from dotenv import load_dotenv
from uagents_core.utils.registration import (
    register_chat_agent,
    RegistrationRequestCredentials,
)

load_dotenv()

AGENT_ENDPOINT = os.environ.get("AGENT_ENDPOINT", "http://127.0.0.1:8000/submit")


def main():
    ok = register_chat_agent(
        "NovoProteinAI",
        AGENT_ENDPOINT,
        active=True,
        credentials=RegistrationRequestCredentials(
            agentverse_api_key=os.environ["AGENTVERSE_KEY"],
            agent_seed_phrase=os.environ["AGENT_SEED"],
        ),
        description="Turns a plain-English vaccine/therapeutic goal into a "
        "structured target (PDB id, chain, epitope) with citations.",
    )
    print("Registration succeeded" if ok else "Registration returned False")


if __name__ == "__main__":
    main()
