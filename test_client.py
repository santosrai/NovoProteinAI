from uagents import Agent, Context
from pymol_uagent.protocols import (
    PingRequest,
    PingResponse,
    LoadStructureRequest,
    LoadStructureResponse,
)

import os
PYMOL_AGENT = os.environ.get("PYMOL_AGENT_ADDRESS", "agent1q0dgdfdwgg8athflrau847zkpf3fa8axsz6uq74vsp4pe57cg9mkys39luq")

client = Agent(
    name="test-client",
    seed="test-client-seed-abc123",
    port=8001,
    agentverse=f"{os.environ.get('AGENTVERSE_API_KEY', '')}@https://agentverse.ai",
    mailbox=True,
)


@client.on_event("startup")
async def start(ctx: Context):
    await ctx.send(PYMOL_AGENT, PingRequest())


@client.on_message(model=PingResponse)
async def got_ping(ctx: Context, sender: str, msg: PingResponse):
    ctx.logger.info(f"PING OK: {msg.version}")
    await ctx.send(PYMOL_AGENT, LoadStructureRequest(source="2HHB"))


@client.on_message(model=LoadStructureResponse)
async def got_load(ctx: Context, sender: str, msg: LoadStructureResponse):
    ctx.logger.info(f"LOAD: {msg}")


if __name__ == "__main__":
    client.run()
