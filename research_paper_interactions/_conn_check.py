"""Quick PubMed / NCBI E-utilities connectivity + full-text check.

No Redis and no embeddings: this only exercises the fetch/parse layer so you can
confirm you actually retrieved the *body text* under each section.

Verifies, in order:
  * esearch  -> can we reach NCBI and get PMIDs for a topic?
  * efetch   -> can we fetch + parse the papers?
And for every paper it prints, per section, the character count and a snippet of
the text, plus whether it came back as PMC full text or abstract-only.

Run:
    python research_paper_interactions/_conn_check.py
    python research_paper_interactions/_conn_check.py "protein language model"
    python research_paper_interactions/_conn_check.py "protein language model" 5
"""

import sys

try:  # package mode
    from . import pubmed
except ImportError:  # run directly as a script
    import pubmed

SNIPPET = 160  # chars of body text to show per section


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    topic = sys.argv[1] if len(sys.argv) > 1 else "de novo protein design"
    retmax = int(sys.argv[2]) if len(sys.argv) > 2 else 3
    print(f"topic: {topic!r}  retmax={retmax}")
    print(f"api_key set: {bool(pubmed.API_KEY)}  tool={pubmed.TOOL!r}  "
          f"email={pubmed.EMAIL or '(none)'}")

    try:
        pmids = pubmed.esearch(topic, retmax=retmax)
    except Exception as exc:
        print(f"esearch FAILED: {type(exc).__name__}: {exc}")
        sys.exit(1)

    if not pmids:
        print("esearch OK but returned 0 PMIDs (try a different topic).")
        return
    print(f"esearch OK -> PMIDs: {pmids}\n")

    try:
        papers = pubmed.fetch_papers(pmids, prefer_fulltext=True)
    except Exception as exc:
        print(f"efetch FAILED: {type(exc).__name__}: {exc}")
        sys.exit(1)

    full_text_count = 0
    for paper in papers:
        meta = paper["meta"]
        if meta.get("source") == "pmc":
            full_text_count += 1
        total_chars = sum(len(text) for _, text in paper["sections"])
        print(f"[{meta.get('source')}] {meta.get('title')!r} ({meta.get('year')})")
        print(f"    pmid={meta.get('pmid')} pmcid={meta.get('pmcid') or '(none)'} "
              f"sections={len(paper['sections'])} total_chars={total_chars}")
        # The actual body text under each section — this is the full-text proof.
        for name, text in paper["sections"]:
            snippet = text[:SNIPPET].replace("\n", " ")
            print(f"      - {name!r:16} {len(text):>6} chars | {snippet}...")
        print()

    print(f"PUBMED OK -> {full_text_count}/{len(papers)} papers returned PMC full text "
          f"(the rest are abstract-only).")
    if full_text_count == 0:
        print("Tip: none were open-access. Try an OA-heavy topic like "
              "'protein language model' to see multi-section full text.")


if __name__ == "__main__":
    main()
