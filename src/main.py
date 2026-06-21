"""Railway entrypoint: run the public WebSocket relay + the Fetch.ai uAgent.

One container hosts two things in the same process:

  * FastAPI relay (uvicorn) on 0.0.0.0:$PORT  -> the public surface the local
    PyMOL plugin connects to (wss://<app>/plugin) and a health endpoint.
  * The NovoProteinAI uAgent (Agentverse mailbox) -> the chat front-end.

The relay runs on the main thread's event loop (so `relay._loop` is captured
for cross-thread tool calls). The uAgent runs in a background thread with its
own loop; its synchronous PyMOL tools schedule coroutines onto the relay loop
via asyncio.run_coroutine_threadsafe.

Env:
  PORT          - injected by Railway (default 8000)
  AGENT_SEED    - required to run the uAgent; if unset, only the relay runs
  ANTHROPIC_API_KEY / ASI_ONE_API_KEY - as used by the agent
"""

import logging
import os
import threading

import uvicorn

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

logging.basicConfig(
    level=getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("novoproteinai.main")


def _run_agent():
    """Run the uAgent (blocking) in its own thread/loop.

    Python 3.12 no longer auto-creates an event loop in non-main threads, and
    uagents.Agent() calls asyncio.get_event_loop() at construction time. So we
    must create and install a loop for this thread before building the agent.
    """
    import asyncio

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    try:
        from src.research_agent import build_agent
    except ImportError:
        from research_agent import build_agent

    logger.info("Starting NovoProteinAI uAgent...")
    build_agent().run()


def main():
    transport = os.environ.get("PYMOL_TRANSPORT", "relay").lower()
    port = int(os.environ.get("PORT", "8000"))

    # Local mode: the agent talks to PyMOL directly over localhost TCP (or a
    # tunnel host set in PYMOL_HOST). No public relay is needed, so just run
    # the agent in the main thread.
    if transport in ("local", "direct", "mcp"):
        if not os.environ.get("AGENT_SEED"):
            raise SystemExit("AGENT_SEED is required to run the agent.")
        logger.info(
            "Local mode (PYMOL_TRANSPORT=%s): running agent only, no relay.",
            transport,
        )
        _run_agent()  # blocks until the agent stops
        return

    # Relay (public) mode: relay on the main thread, agent in a background
    # thread. Used when deployed publicly (e.g. Railway).
    if os.environ.get("AGENT_SEED"):
        agent_thread = threading.Thread(target=_run_agent, daemon=True)
        agent_thread.start()
    else:
        logger.warning(
            "AGENT_SEED not set; running relay only (no chat agent). "
            "Set AGENT_SEED to enable the Agentverse chat agent."
        )

    logger.info("Starting relay (uvicorn) on 0.0.0.0:%d", port)
    uvicorn.run("src.relay:app", host="0.0.0.0", port=port, log_level="info")


if __name__ == "__main__":
    main()
