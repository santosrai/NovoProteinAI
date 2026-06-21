"""Tests for the LLM intent parser in pymol_uagent.agent.

Run:
    export ANTHROPIC_API_KEY=sk-ant-...
    python3 -m pytest tests/test_nlp_parser.py -v
"""
import os
import pytest

from pymol_uagent.agent import _parse_chat_command


LLM_AVAILABLE = bool(os.environ.get("ANTHROPIC_API_KEY", "").startswith("sk-ant-"))
pytestmark = [
    pytest.mark.skipif(not LLM_AVAILABLE, reason="ANTHROPIC_API_KEY not set"),
    pytest.mark.asyncio,
]


async def test_load_natural():
    tool, params = await _parse_chat_command("load protein 2HHB from the database")
    assert tool == "load_structure"
    assert params["source"] == "2HHB"


async def test_color_inverted_order():
    tool, params = await _parse_chat_command("color the chain A red")
    assert tool == "color_selection"
    assert params["color"] == "red"
    assert params["selection"] == "chain A"


async def test_color_implicit_all():
    tool, params = await _parse_chat_command("paint everything blue")
    assert tool == "color_selection"
    assert params["color"] == "blue"


async def test_render_casual():
    tool, _ = await _parse_chat_command("can you take a screenshot please?")
    assert tool == "render_image"


async def test_ping_question():
    tool, _ = await _parse_chat_command("is pymol connected?")
    assert tool == "ping_pymol"


async def test_chain_b_green():
    tool, params = await _parse_chat_command("highlight chain B in green")
    assert tool == "color_selection"
    assert params["color"] == "green"
    assert "B" in params["selection"]


async def test_unknown_graceful():
    tool, params = await _parse_chat_command("what is the weather today?")
    assert tool == ""
