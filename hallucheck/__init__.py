"""LLM Hallucination Checker — force closed-vocabulary citations, substitute the
real authority text, and inspect whether each conclusion is actually supported.

Corpus-agnostic: the generic engine, scanner, dead-link checker, attestation and
harness guards live here; a *corpus adapter* (see ``hallucheck.adapter.Adapter``)
supplies the closed vocabulary, the authority resolver and the citation patterns.
A Maine probate adapter ships under ``adapters/maine`` as a reference.

Not legal advice.
"""
from . import (  # noqa: F401
               adapter,
               attest,
               benchmark,
               brief,
               conformance,
               courtlistener,
               embed,
               guard,
               inspector,
               links,
               research,
               scan,
               sources,
)
from .disclaimer import LIBRARY_DISCLAIMER, SHORT_DISCLAIMER  # noqa: F401

__version__ = "0.8.1"
