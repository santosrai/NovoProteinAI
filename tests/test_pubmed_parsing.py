"""Offline tests for research_paper_interactions.pubmed XML parsing.

No network access: we feed canned PubMed/PMC XML through the parsing helpers,
so these run fast and deterministically.
"""

import os
import sys
import xml.etree.ElementTree as ET

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# pubmed only depends on `requests` + stdlib, so it imports without the heavy
# redis/embedding stack.
from research_paper_interactions import pubmed


PUBMED_XML = b"""<?xml version="1.0"?>
<PubmedArticleSet>
  <PubmedArticle>
    <MedlineCitation>
      <PMID>12345678</PMID>
      <Article>
        <Journal><JournalIssue><PubDate><Year>2021</Year></PubDate></JournalIssue></Journal>
        <ArticleTitle>Structure of the <i>TNF-alpha</i> receptor complex</ArticleTitle>
        <Abstract>
          <AbstractText Label="BACKGROUND">TNF-alpha drives inflammation.</AbstractText>
          <AbstractText Label="RESULTS">We solved the complex at 2.1 A.</AbstractText>
        </Abstract>
        <AuthorList>
          <Author><LastName>Doe</LastName><ForeName>Jane</ForeName></Author>
          <Author><CollectiveName>The Structure Consortium</CollectiveName></Author>
        </AuthorList>
      </Article>
    </MedlineCitation>
    <PubmedData>
      <ArticleIdList>
        <ArticleId IdType="doi">10.1234/abcd</ArticleId>
        <ArticleId IdType="pmc">PMC7654321</ArticleId>
      </ArticleIdList>
    </PubmedData>
  </PubmedArticle>
</PubmedArticleSet>
"""

PMC_XML = b"""<?xml version="1.0"?>
<pmc-articleset>
  <article>
    <body>
      <sec>
        <title>Introduction</title>
        <p>TNF-alpha is a cytokine.</p>
        <sec><title>Sub</title><p>Nested context here.</p></sec>
      </sec>
      <sec>
        <title>Methods</title>
        <p>Crystals were grown at 4 C.</p>
      </sec>
    </body>
  </article>
</pmc-articleset>
"""

PMC_XML_NO_BODY = b"""<?xml version="1.0"?>
<pmc-articleset><article><front/></article></pmc-articleset>"""


def _article():
    return ET.fromstring(PUBMED_XML).find(".//PubmedArticle")


def test_parse_meta():
    meta = pubmed._parse_meta(_article(), "12345678")
    assert meta["paper_id"] == "pmid_12345678"
    assert meta["pmid"] == "12345678"
    assert meta["title"] == "Structure of the TNF-alpha receptor complex"
    assert meta["doi"] == "10.1234/abcd"
    assert meta["pmcid"] == "PMC7654321"
    assert meta["year"] == 2021
    assert meta["authors"] == ["Doe Jane", "The Structure Consortium"]


def test_parse_abstract_keeps_labels():
    abstract = pubmed._parse_abstract(_article())
    assert "BACKGROUND: TNF-alpha drives inflammation." in abstract
    assert "RESULTS: We solved the complex at 2.1 A." in abstract


def test_sections_from_body_flattens_nested():
    body = ET.fromstring(PMC_XML).find(".//article/body")
    sections = pubmed._sections_from_body(body)
    names = [name for name, _ in sections]
    assert names == ["introduction", "methods"]
    intro_text = sections[0][1]
    # Nested subsection text is pulled into the parent section exactly once.
    assert "TNF-alpha is a cytokine." in intro_text
    assert "Nested context here." in intro_text


def test_fetch_pmc_fulltext_uses_numeric_id(monkeypatch):
    captured = {}

    class _Resp:
        content = PMC_XML

    def fake_get(url, params):
        captured.update(params)
        return _Resp()

    monkeypatch.setattr(pubmed, "_get", fake_get)
    sections = pubmed.fetch_pmc_fulltext("PMC7654321")
    assert captured["db"] == "pmc"
    assert captured["id"] == "7654321"  # PMC prefix stripped
    assert [n for n, _ in sections] == ["introduction", "methods"]


def test_fetch_pmc_fulltext_no_body_returns_empty(monkeypatch):
    class _Resp:
        content = PMC_XML_NO_BODY

    monkeypatch.setattr(pubmed, "_get", lambda url, params: _Resp())
    assert pubmed.fetch_pmc_fulltext("PMC1") == []


def test_build_paper_prefers_fulltext(monkeypatch):
    monkeypatch.setattr(
        pubmed, "fetch_pmc_fulltext", lambda pmcid: [("introduction", "Full text.")]
    )
    paper = pubmed._build_paper(_article(), "12345678", prefer_fulltext=True)
    assert paper["meta"]["source"] == "pmc"
    section_names = [name for name, _ in paper["sections"]]
    assert section_names[0] == "abstract"  # abstract always first
    assert "introduction" in section_names


def test_build_paper_falls_back_to_abstract(monkeypatch):
    # PMC returns nothing (not open-access) -> abstract only, source stays pubmed.
    monkeypatch.setattr(pubmed, "fetch_pmc_fulltext", lambda pmcid: [])
    paper = pubmed._build_paper(_article(), "12345678", prefer_fulltext=True)
    assert paper["meta"]["source"] == "pubmed"
    assert [n for n, _ in paper["sections"]] == ["abstract"]
