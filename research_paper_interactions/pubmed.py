"""PubMed / PMC client built on NCBI E-utilities (no PDF download).

Papers are fetched and parsed directly from the XML that E-utilities returns:

  * ``esearch``  -> PMIDs matching a topic
  * ``efetch``   (db=pubmed) -> title, abstract, authors, year, DOI, PMCID
  * ``efetch``   (db=pmc)    -> full-text JATS XML for open-access papers

The full text is parsed straight from the JATS ``<body>`` into
``(section_name, text)`` pairs, so the downstream ingester never has to touch a
PDF. Papers that are not open-access fall back to their abstract.

NCBI etiquette: set ``NCBI_API_KEY`` (and optionally ``NCBI_EMAIL`` /
``NCBI_TOOL``) in the environment to lift the rate limit from 3 to 10 req/s.
"""

import os
import re
import time
import xml.etree.ElementTree as ET

import requests
from dotenv import load_dotenv

# Load this package's own .env (see .env.example) so NCBI_* are available even
# when the process didn't load it elsewhere. Done before reading the vars below.
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
ESEARCH = f"{EUTILS}/esearch.fcgi"
EFETCH = f"{EUTILS}/efetch.fcgi"

HTTP_TIMEOUT = 30

API_KEY = os.getenv("NCBI_API_KEY", "")
EMAIL = os.getenv("NCBI_EMAIL", "")
TOOL = os.getenv("NCBI_TOOL", "NovoProteinAI")

# Without an API key NCBI allows 3 req/s; with one, 10 req/s. Sleep just enough
# to stay under the limit so a batch of fetches doesn't get throttled (HTTP 429).
_MIN_INTERVAL = 0.11 if API_KEY else 0.34
_last_request = 0.0


def _common_params() -> dict:
    """Identifying params NCBI asks every E-utilities caller to send."""
    params = {"tool": TOOL}
    if API_KEY:
        params["api_key"] = API_KEY
    if EMAIL:
        params["email"] = EMAIL
    return params


def _get(url: str, params: dict) -> requests.Response:
    """Rate-limited GET against E-utilities."""
    global _last_request
    wait = _MIN_INTERVAL - (time.monotonic() - _last_request)
    if wait > 0:
        time.sleep(wait)
    resp = requests.get(
        url, params={**_common_params(), **params}, timeout=HTTP_TIMEOUT
    )
    _last_request = time.monotonic()
    resp.raise_for_status()
    return resp


# --- text helpers -----------------------------------------------------------
def _clean(text: str) -> str:
    """Collapse whitespace; JATS/PubMed text is full of newlines and padding."""
    return re.sub(r"\s+", " ", text or "").strip()


def _node_text(node) -> str:
    """All descendant text of an XML node, in document order (handles markup)."""
    if node is None:
        return ""
    return _clean("".join(node.itertext()))


# --- esearch ----------------------------------------------------------------
def esearch(term: str, retmax: int = 5) -> list[str]:
    """Return PMIDs for `term`, most relevant first."""
    resp = _get(
        ESEARCH,
        {
            "db": "pubmed",
            "term": term,
            "retmax": retmax,
            "retmode": "json",
            "sort": "relevance",
        },
    )
    return resp.json().get("esearchresult", {}).get("idlist", [])


# --- efetch (pubmed): metadata + abstract -----------------------------------
def _parse_year(article) -> int:
    """Best-effort publication year from the several places PubMed stores it."""
    for path in (".//Journal/JournalIssue/PubDate/Year", ".//ArticleDate/Year"):
        year = article.findtext(path)
        if year and year.isdigit():
            return int(year)
    # MedlineDate is a free-text fallback like "2021 Jan-Feb".
    medline = article.findtext(".//Journal/JournalIssue/PubDate/MedlineDate") or ""
    match = re.search(r"\d{4}", medline)
    return int(match.group()) if match else 0


def _parse_authors(article) -> list[str]:
    """'Last First' for each author, or the collective/group name."""
    authors = []
    for author in article.findall(".//AuthorList/Author"):
        last = author.findtext("LastName")
        fore = author.findtext("ForeName")
        if last:
            authors.append(f"{last} {fore}".strip() if fore else last)
        else:
            collective = author.findtext("CollectiveName")
            if collective:
                authors.append(collective)
    return authors


def _parse_abstract(article) -> str:
    """Join AbstractText pieces, prefixing any structured-abstract labels."""
    parts = []
    for node in article.findall(".//Abstract/AbstractText"):
        label = node.get("Label")
        body = _node_text(node)
        if not body:
            continue
        parts.append(f"{label}: {body}" if label else body)
    return " ".join(parts)


def _article_id(article, id_type: str) -> str:
    """Pull an ArticleId of a given type (e.g. 'doi', 'pmc') from PubmedData."""
    for node in article.findall(".//ArticleIdList/ArticleId"):
        if node.get("IdType") == id_type:
            return _clean(node.text or "")
    return ""


def _parse_meta(article, pmid: str) -> dict:
    """Build the metadata dict shared by every chunk of this paper."""
    return {
        "paper_id": f"pmid_{pmid}",
        "pmid": pmid,
        "title": _node_text(article.find(".//ArticleTitle")),
        "authors": _parse_authors(article),
        "doi": _article_id(article, "doi"),
        "pmcid": _article_id(article, "pmc"),
        "year": _parse_year(article),
        "source": "pubmed",
    }


def _efetch_pubmed(pmids: list[str]) -> ET.Element:
    resp = _get(EFETCH, {"db": "pubmed", "id": ",".join(pmids), "retmode": "xml"})
    return ET.fromstring(resp.content)


# --- efetch (pmc): full text ------------------------------------------------
def _sections_from_body(body: ET.Element) -> list[tuple[str, str]]:
    """Flatten a JATS <body> into (section_title, text) pairs.

    Only top-level <sec> elements are iterated; ``itertext`` already pulls in any
    nested subsections, so each top-level section is captured exactly once. Falls
    back to all paragraph text when the body has no <sec> structure.
    """
    sections: list[tuple[str, str]] = []
    for sec in body.findall("sec"):
        title = _clean(sec.findtext("title") or "")
        text = _node_text(sec)
        if text:
            sections.append((title.lower() or "body", text))
    if not sections:
        text = " ".join(_node_text(p) for p in body.findall(".//p"))
        if text.strip():
            sections.append(("body", text))
    return sections


def fetch_pmc_fulltext(pmcid: str) -> list[tuple[str, str]]:
    """Return full-text (section, text) pairs for an open-access PMC article.

    Returns an empty list if the article isn't in the open-access subset (the
    JATS then has no <body>), so callers can fall back to the abstract.
    """
    numeric = pmcid.replace("PMC", "")
    resp = _get(EFETCH, {"db": "pmc", "id": numeric, "retmode": "xml"})
    root = ET.fromstring(resp.content)
    body = root.find(".//article/body")
    return _sections_from_body(body) if body is not None else []


# --- public: fetch one or many papers ---------------------------------------
def _build_paper(article, pmid: str, prefer_fulltext: bool) -> dict:
    meta = _parse_meta(article, pmid)
    sections: list[tuple[str, str]] = []

    abstract = _parse_abstract(article)
    if abstract:
        sections.append(("abstract", abstract))

    if prefer_fulltext and meta["pmcid"]:
        try:
            fulltext = fetch_pmc_fulltext(meta["pmcid"])
        except Exception:  # noqa: BLE001 - any PMC hiccup -> abstract-only
            fulltext = []
        if fulltext:
            meta["source"] = "pmc"
            sections.extend(fulltext)

    # Drop empty sections; title is always retrievable via metadata.
    sections = [(name, _clean(text)) for name, text in sections if text.strip()]
    return {"meta": meta, "sections": sections}


def fetch_papers(pmids: list[str], prefer_fulltext: bool = True) -> list[dict]:
    """Fetch + parse a batch of PMIDs into ``{"meta", "sections"}`` dicts.

    Metadata/abstracts come from one batched efetch; full text (when available
    and requested) is fetched per PMCID from the PMC open-access service.
    """
    if not pmids:
        return []
    root = _efetch_pubmed(pmids)
    papers = []
    for article in root.findall(".//PubmedArticle"):
        pmid = article.findtext(".//MedlineCitation/PMID") or ""
        papers.append(_build_paper(article, pmid, prefer_fulltext))
    return papers


def fetch_paper(pmid: str, prefer_fulltext: bool = True) -> dict:
    """Fetch + parse a single PMID (convenience wrapper around fetch_papers)."""
    papers = fetch_papers([pmid], prefer_fulltext=prefer_fulltext)
    return papers[0] if papers else {"meta": {"paper_id": f"pmid_{pmid}"}, "sections": []}
