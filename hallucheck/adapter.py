"""The corpus-adapter seam.

The generic engine knows nothing about a specific body of law/sources. A *corpus
adapter* supplies everything domain-specific:

  - the closed vocabulary (which citation KEYs are allowed),
  - how to resolve a KEY to authority text (and flag a dead link),
  - the citation surface forms for the deterministic scanner,
  - whether a URL belongs to the trusted index (fabricated-URL detection),
  - a disclaimer and a config digest (for attestation).

Implement :class:`Adapter` (or duck-type it) and register the class so the CLI and
guards can load it by name. The Maine probate adapter under ``adapters/maine`` is
a complete reference.
"""
from __future__ import annotations

import importlib
from typing import Protocol, runtime_checkable

_REGISTRY: dict[str, str] = {
    # name -> "dotted.module:factory"
    "maine": "adapters.maine.adapter:MaineProbateAdapter",
    "courtlistener": "adapters.courtlistener.adapter:CourtListenerCaselawAdapter",
}


@runtime_checkable
class Adapter(Protocol):
    name: str
    disclaimer: str

    def build_vocabulary(self, scope: str | None = None) -> dict:
        """KEY -> metadata ({kind, cite, title/name, url, note, ...}) for ``scope``."""

    def resolve(self, key: str, *, fetch_text: bool = True) -> dict | None:
        """Resolve KEY to an authority ``{cite, title, url, text, text_verified}``;
        ``{dead_link: True, text: None}`` when the source URL is dead; ``None`` when
        unresolvable."""

    def citation_spans(self, text: str, *, scope: str | None = None) -> list[dict]:
        """Deterministic, offline. Find citation-shaped spans in ``text`` and
        resolve each against the closed index. Each hit:
        ``{raw, cite, kind, span:[s,e], resolves: bool, in_vocab?: bool}``."""

    def url_in_index(self, url: str) -> bool | None:
        """Offline: ``True``/``False`` whether a source URL is in the trusted index,
        or ``None`` when the URL isn't one this adapter can judge."""

    def index_urls(self, scope: str = "used") -> dict:
        """``{url: [cites]}`` of authority URLs, for the dead-link audit."""

    def config_digest(self) -> str:
        """Short hash of the index/data revision (recorded in attestation receipts)."""


def register(name: str, target: str) -> None:
    """Register ``name`` -> ``"dotted.module:factory"``."""
    _REGISTRY[name] = target


def load(spec: str):
    """Load an adapter by registered name or ``"dotted.module:factory"``."""
    target = _REGISTRY.get(spec, spec)
    if ":" not in target:
        raise ValueError(f"unknown adapter {spec!r}; use a registered name "
                         f"({', '.join(sorted(_REGISTRY))}) or 'module:factory'")
    mod, _, factory = target.partition(":")
    return getattr(importlib.import_module(mod), factory)()
