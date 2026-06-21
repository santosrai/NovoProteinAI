"""Redis-backed paper ingestion and vector search for NovoProteinAI.

This package can be used two ways:

  * As a package (preferred):  ``from redis_interactions.search import search``
  * As standalone scripts:     ``python search.py "question"`` (run from this
    directory)

To support both, the modules import their siblings with a try/except: the
relative import works in package mode, and the bare import works when a module
is executed directly as ``__main__`` (with this directory on ``sys.path``).
"""
