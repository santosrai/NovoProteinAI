"""Unit tests for src/research_agent.run_research (no network access)."""

import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src import research_agent as ra


REQUIRED_KEYS = {
    "target_name",
    "pdb_id",
    "chain",
    "epitope_residues",
    "binder_pdb_ids",
    "explanation",
    "citations",
}


@pytest.fixture(autouse=True)
def no_asi_key(monkeypatch):
    """Default: no ASI:One key, so the keyword fallback path is exercised."""
    monkeypatch.delenv("ASI_ONE_API_KEY", raising=False)


def _assert_contract(result):
    assert isinstance(result, dict)
    assert set(result.keys()) == REQUIRED_KEYS
    assert isinstance(result["epitope_residues"], list)
    assert isinstance(result["binder_pdb_ids"], list)
    assert isinstance(result["explanation"], str) and result["explanation"]
    assert isinstance(result["citations"], list)
    for c in result["citations"]:
        assert set(c.keys()) == {"title", "pmid", "url"}


def test_happy_path(monkeypatch):
    monkeypatch.setattr(ra, "search_pdb", lambda q: ["6VXX", "1ABC"])
    monkeypatch.setattr(ra, "pdb_exists", lambda pid: pid == "6VXX")
    monkeypatch.setattr(
        ra,
        "search_pubmed",
        lambda term, retmax=3: [
            {"title": "t", "pmid": "1", "url": "https://pubmed.ncbi.nlm.nih.gov/1/"}
        ],
    )

    result = ra.run_research("build a vaccine for COVID")

    _assert_contract(result)
    assert result["pdb_id"] == "6VXX"
    assert result["chain"] == "A"
    assert len(result["citations"]) == 1


def test_no_pdb_match(monkeypatch):
    monkeypatch.setattr(ra, "search_pdb", lambda q: [])
    monkeypatch.setattr(ra, "pdb_exists", lambda pid: False)
    monkeypatch.setattr(ra, "search_pubmed", lambda term, retmax=3: [])

    result = ra.run_research("something with no structure")

    _assert_contract(result)
    assert result["pdb_id"] is None
    assert result["chain"] is None
    assert result["epitope_residues"] == []
    assert "No matching PDB" in result["explanation"]


def test_fallback_without_asi_key(monkeypatch):
    """With no ASI key, asi_one returns '' and the keyword path still works."""
    monkeypatch.setattr(ra, "search_pdb", lambda q: ["6VXX"])
    monkeypatch.setattr(ra, "pdb_exists", lambda pid: True)
    monkeypatch.setattr(ra, "search_pubmed", lambda term, retmax=3: [])

    assert ra.asi_one("anything") == ""

    result = ra.run_research("build a vaccine for COVID")
    _assert_contract(result)
    assert result["pdb_id"] == "6VXX"
    # target_name came from the keyword fallback (filler words stripped).
    assert "vaccine" not in result["target_name"].lower()


def test_keyword_target_strips_filler():
    assert ra._keyword_target("build a vaccine for COVID") == "covid"
    # Empty after stripping -> falls back to the original goal.
    assert ra._keyword_target("vaccine for the") == "vaccine for the"


def test_run_research_handles_empty_goal(monkeypatch):
    monkeypatch.setattr(ra, "search_pdb", lambda q: [])
    monkeypatch.setattr(ra, "pdb_exists", lambda pid: False)
    monkeypatch.setattr(ra, "search_pubmed", lambda term, retmax=3: [])

    result = ra.run_research("")
    _assert_contract(result)
    assert result["pdb_id"] is None
