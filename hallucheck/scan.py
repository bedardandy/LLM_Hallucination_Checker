"""Deterministic citation scanner — the safety net (no LLM, no network).

The forced ``[[REF:]]`` protocol guarantees correctness only for cites a model
chose to wrap. A model can still drop a bare citation or a fabricated URL into
prose. This module supplies the *generic mechanism* — placeholder awareness,
leaked/unresolvable/out-of-vocab bucketing, and URL classification — while the
corpus adapter supplies the *citation patterns* (``adapter.citation_spans``) and
the URL index check (``adapter.url_in_index``).
"""
from __future__ import annotations

import re

from . import inspector

_RE_URL = re.compile(r"https?://[^\s)>\]\"'}]+")
_PLACEHOLDER_HOSTS = ("example.com", "example.org", "example.net", "example.edu",
                      "example", "test.com", "foo.com", "foo.bar", "domain.com",
                      "yoursite.com", "localhost")


def scan_urls(text: str, adapter, *, check_live: bool = False) -> list[dict]:
    """Classify URL strings: ``placeholder`` (example.com…), ``fabricated`` (an
    index-style URL the adapter says isn't in the index), ``known``, or
    ``unknown``. ``check_live`` probes unknown/fabricated ones (network)."""
    from . import links
    hits = []
    for m in _RE_URL.finditer(text or ""):
        url = m.group(0).rstrip(".,);]'\"")
        host = re.sub(r"^https?://", "", url).split("/")[0].lower()
        if (host in _PLACEHOLDER_HOSTS or host.endswith(".test")
                or host.endswith(".example") or host.endswith(".invalid")):
            klass = "placeholder"
        else:
            in_idx = adapter.url_in_index(url)
            klass = {True: "known", False: "fabricated"}.get(in_idx, "unknown")
        rec = {"url": url, "span": [m.start(), m.end()], "class": klass}
        if check_live and klass in ("unknown", "fabricated"):
            rec["link_status"] = links.check_url(url)["status"]
        hits.append(rec)
    return hits


def report(text: str, adapter, *, scope: str | None = None,
           check_live: bool = False) -> dict:
    """Scan ``text`` and bucket: ``leaked`` (citation-shaped, outside any
    ``[[REF:]]``), ``unresolvable`` (not in the index), ``out_of_vocab`` (resolves
    but not in ``scope``'s vocabulary), and ``fabricated_urls``."""
    text = text or ""
    hits = adapter.citation_spans(text, scope=scope)
    ph_spans = [(m.start(), m.end()) for m in inspector.PLACEHOLDER.finditer(text)]
    for h in hits:
        s, e = h["span"]
        h["in_placeholder"] = any(ps <= s and e <= pe for ps, pe in ph_spans)
    uses_protocol = bool(ph_spans)
    leaked = sorted({h["cite"] for h in hits if uses_protocol and not h["in_placeholder"]})
    unresolvable = sorted({h["cite"] for h in hits if not h["resolves"]})
    url_hits = scan_urls(text, adapter, check_live=check_live)
    out = {
        "hits": hits, "uses_protocol": uses_protocol,
        "leaked": leaked, "unresolvable": unresolvable,
        "urls": url_hits,
        "fabricated_urls": sorted({h["url"] for h in url_hits
                                   if h["class"] in ("placeholder", "fabricated")}),
        "dead_urls": sorted({h["url"] for h in url_hits if h.get("link_status") == "dead"}),
    }
    if scope is not None:
        out["out_of_vocab"] = sorted({h["cite"] for h in hits
                                      if h["resolves"] and not h.get("in_vocab")})
    return out
