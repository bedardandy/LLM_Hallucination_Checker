"""LLM Hallucination Checker — force closed-vocabulary citations, substitute the
real authority text, and inspect whether each conclusion is actually supported.

Corpus-agnostic: the generic engine, scanner, dead-link checker, attestation and
harness guards live here; a *corpus adapter* (see ``hallucheck.adapter.Adapter``)
supplies the closed vocabulary, the authority resolver and the citation patterns.
A Maine probate adapter ships under ``adapters/maine`` as a reference.

Not legal advice.
"""
from . import adapter, attest, guard, inspector, links, scan      # noqa: F401

__version__ = "0.1.0"
