"""Tests for the NLP intent parser in pymol_uagent.agent.

Run:
    # Regex fallback only (no API key needed):
    python3 -m pytest tests/test_nlp_parser.py -v -k "regex"

    # Full LLM test (requires ANTHROPIC_API_KEY in env):
    export ANTHROPIC_API_KEY=sk-ant-...
    python3 -m pytest tests/test_nlp_parser.py -v
"""
import asyncio
import os
import pytest

from pymol_uagent.agent import _parse_with_regex, _parse_chat_command


# ---------------------------------------------------------------------------
# Regex fallback tests (always run, no API key needed)
# ---------------------------------------------------------------------------

class TestRegexParser:
    def test_load_standard(self):
        assert _parse_with_regex("load 2HHB") == (
            "load_structure", {"source": "2HHB", "object_name": ""}
        )

    def test_load_with_words_around(self):
        tool, params = _parse_with_regex("fetch 1ABC from PDB")
        assert tool == "load_structure"
        assert params["source"] == "1ABC"

    def test_load_open_synonym(self):
        tool, params = _parse_with_regex("open structure 4HHB")
        assert tool == "load_structure"
        assert params["source"] == "4HHB"

    def test_color_after_keyword(self):
        tool, params = _parse_with_regex("color red chain A")
        assert tool == "color_selection"
        assert params["color"] == "red"
        assert params["selection"] == "chain A"

    def test_color_before_keyword(self):
        # "color the chain A red" — color word comes after chain
        tool, params = _parse_with_regex("color the chain A red")
        assert tool == "color_selection"
        assert params["color"] == "red"
        assert params["selection"] == "chain A"

    def test_color_chain_word_order_inverted(self):
        tool, params = _parse_with_regex("color chain A to red")
        assert tool == "color_selection"
        assert params["color"] == "red"
        assert params["selection"] == "chain A"

    def test_color_no_chain(self):
        tool, params = _parse_with_regex("make everything blue")
        assert tool == "color_selection"
        assert params["color"] == "blue"
        assert params["selection"] == "all"

    def test_color_highlight_synonym(self):
        tool, params = _parse_with_regex("highlight the protein in green")
        assert tool == "color_selection"
        assert params["color"] == "green"

    def test_color_chain_not_captured_as_color(self):
        # "color the chain red" — "red" should be color, selection = all (no valid chain ID)
        tool, params = _parse_with_regex("color the chain red")
        assert tool == "color_selection"
        assert params["color"] == "red"
        assert params["selection"] == "all"

    def test_render_keyword(self):
        tool, params = _parse_with_regex("render")
        assert tool == "render_image"
        assert params["width"] == 800
        assert params["height"] == 600

    def test_render_screenshot_synonym(self):
        tool, _ = _parse_with_regex("take a screenshot")
        assert tool == "render_image"

    def test_render_picture_synonym(self):
        tool, _ = _parse_with_regex("take a picture of the molecule")
        assert tool == "render_image"

    def test_ping_keyword(self):
        tool, _ = _parse_with_regex("ping")
        assert tool == "ping_pymol"

    def test_ping_status_synonym(self):
        tool, _ = _parse_with_regex("status")
        assert tool == "ping_pymol"

    def test_ping_alive_synonym(self):
        tool, _ = _parse_with_regex("is pymol alive?")
        assert tool == "ping_pymol"

    def test_unknown_returns_empty(self):
        tool, params = _parse_with_regex("hello there")
        assert tool == ""
        assert params == {}


# ---------------------------------------------------------------------------
# LLM parser tests (skipped when no API key)
# ---------------------------------------------------------------------------

LLM_AVAILABLE = bool(os.environ.get("ANTHROPIC_API_KEY", "").startswith("sk-ant-"))


@pytest.mark.skipif(not LLM_AVAILABLE, reason="ANTHROPIC_API_KEY not set")
class TestLLMParser:
    def _run(self, text):
        return asyncio.run(_parse_chat_command(text))

    def test_load_natural(self):
        tool, params = self._run("load protein 2HHB from the database")
        assert tool == "load_structure"
        assert params["source"] == "2HHB"

    def test_color_inverted_order(self):
        tool, params = self._run("color the chain A red")
        assert tool == "color_selection"
        assert params["color"] == "red"
        assert params["selection"] == "chain A"

    def test_color_implicit_all(self):
        tool, params = self._run("paint everything blue")
        assert tool == "color_selection"
        assert params["color"] == "blue"

    def test_render_casual(self):
        tool, _ = self._run("can you take a screenshot please?")
        assert tool == "render_image"

    def test_ping_question(self):
        tool, _ = self._run("is pymol connected?")
        assert tool == "ping_pymol"

    def test_chain_b_green(self):
        tool, params = self._run("highlight chain B in green")
        assert tool == "color_selection"
        assert params["color"] == "green"
        assert "B" in params["selection"]

    def test_unknown_graceful(self):
        tool, params = self._run("what is the weather today?")
        assert tool == ""
