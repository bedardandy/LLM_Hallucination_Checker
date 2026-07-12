"""Deterministic citation scanner — the safety net (no LLM, no network).

The forced ``[[REF:]]`` protocol guarantees correctness only for cites a model
chose to wrap. A model can still drop a bare citation or a fabricated URL into
prose. This module supplies the *generic mechanism* — placeholder awareness,
leaked/unresolvable/out-of-vocab bucketing, and URL classification — while the
corpus adapter supplies the *citation patterns* (``adapter.citation_spans``) and
the URL index check (``adapter.url_in_index``).

It also includes broad legal-citation heuristics for opposing briefs and mixed
authority sets. Those generic hits are intentionally classified as
``unclassified_citations`` rather than auto-resolved: agency rules, court rules,
secondary sources, federal authorities, and reporter cites should be routed to a
trusted adapter/index or manual review instead of silently passing.
"""
from __future__ import annotations

import re

from . import inspector
from .textnorm import clean

_RE_URL = re.compile(r"https?://[^\s)>\]\"'}]+")
_PLACEHOLDER_HOSTS = ("example.com", "example.org", "example.net", "example.edu",
                      "example", "test.com", "foo.com", "foo.bar", "domain.com",
                      "yoursite.com", "localhost")
_GENERIC_CITATION_PATTERNS: tuple[tuple[str, re.Pattern], ...] = (
    ("usc", re.compile(r"\b\d+\s+U\.S\.C\.\s*§+\s*[\w\-.]+(?:\([\w\-.]+\))*", re.I)),
    ("cfr", re.compile(r"\b\d+\s+C\.F\.R\.\s*§+\s*[\w\-.]+(?:\([\w\-.]+\))*", re.I)),
    ("federal_rule", re.compile(
        r"\bFed\.\s*R\.\s*(?:Civ|Crim|Evid|App|Bankr)\.\s*P\.\s*\d+(?:\.\d+)?(?:\([\w\-.]+\))*",
        re.I)),
    ("court_rule", re.compile(
        r"\b(?:Local\s+Rule|L\.R\.|Rule)\s+\d+(?:\.\d+)?(?:\([\w\-.]+\))*", re.I)),
    ("administrative_code", re.compile(
        r"\b\d+\s+[A-Z][A-Za-z. ]{0,30}(?:Admin(?:istrative)?\.?\s+Code|Code\s+R\.?|Regs?\.?)\s*"
        r"§+?\s*[\w\-.]+(?:\([\w\-.]+\))*", re.I)),
    ("reporter", re.compile(
        r"\b\d+\s+(?:U\.S\.|S\.\s*Ct\.|L\.\s*Ed\.\s*2d|F\.\s?\d?d|F\.\s?Supp\.\s?\d?d|"
        r"N\.E\.\d?d|N\.W\.\d?d|S\.E\.\d?d|S\.W\.\d?d|P\.\d?d|A\.\d?d|So\.\d?d)\s+\d+\b",
        re.I)),
    ("secondary", re.compile(
        r"\b\d+\s+[A-Z][A-Za-z&.'’\- ]{2,60}\s+(?:L\.\s*Rev\.|Law\s+Review|J\.|Journal|Treatise)\s+\d+\b",
        re.I)),
)


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


def generic_citation_spans(text: str, known_hits: list[dict] | None = None) -> list[dict]:
    """Find broad legal-citation shapes not resolved by the active adapter."""
    known_spans = [tuple(h.get("span", ())) for h in known_hits or []]
    out: list[dict] = []
    seen: set[tuple[str, int, int]] = set()
    for kind, pattern in _GENERIC_CITATION_PATTERNS:
        for m in pattern.finditer(text or ""):
            span = (m.start(), m.end())
            if any(_overlaps(span, ks) for ks in known_spans if len(ks) == 2):
                continue
            cite = " ".join(m.group(0).split())
            key = (cite.lower(), span[0], span[1])
            if key in seen:
                continue
            seen.add(key)
            out.append({"cite": cite, "span": [span[0], span[1]], "kind": kind,
                        "resolves": False, "review_required": True})
    return sorted(out, key=lambda h: (h["span"][0], h["span"][1], h["cite"]))


def _overlaps(a: tuple[int, int], b: tuple[int, int]) -> bool:
    return a[0] < b[1] and b[0] < a[1]


def report(text: str, adapter, *, scope: str | None = None,
           check_live: bool = False) -> dict:
    """Scan ``text`` and bucket findings. The text is first normalized
    (:func:`hallucheck.textnorm.clean`) so homoglyph/zero-width evasion can't hide
    a cite. Buckets: ``leaked`` (any citation-shaped span outside a ``[[REF:]]``
    placeholder — i.e. unverified), ``unresolvable`` (not in the trusted index, even
    if wrapped), ``out_of_vocab`` (resolves but not in ``scope``'s vocabulary),
    ``fabricated_urls``, and ``unclassified_citations`` (generic legal citation
    shapes not covered by the active adapter). ``leaked`` is *strict*: an unwrapped
    citation counts even if the draft used no placeholders at all, which is what
    stops the "skip the protocol and mischaracterize in prose" bypass."""
    text = clean(text or "")
    hits = adapter.citation_spans(text, scope=scope)
    generic_hits = generic_citation_spans(text, hits)
    ph_spans = [(m.start(), m.end()) for m in inspector.PLACEHOLDER.finditer(text)]
    for h in hits:
        s, e = h["span"]
        h["in_placeholder"] = any(ps <= s and e <= pe for ps, pe in ph_spans)
    for h in generic_hits:
        s, e = h["span"]
        h["in_placeholder"] = any(ps <= s and e <= pe for ps, pe in ph_spans)
    leaked = sorted({h["cite"] for h in hits if not h["in_placeholder"]})
    url_hits = scan_urls(text, adapter, check_live=check_live)
    out = {
        "hits": hits, "generic_hits": generic_hits, "uses_protocol": bool(ph_spans),
        "leaked": leaked,
        "unresolvable": sorted({h["cite"] for h in hits if not h["resolves"]}),
        "unclassified_citations": sorted({h["cite"] for h in generic_hits}),
        "urls": url_hits,
        "fabricated_urls": sorted({h["url"] for h in url_hits
                                   if h["class"] in ("placeholder", "fabricated")}),
        "unknown_urls": sorted({h["url"] for h in url_hits if h["class"] == "unknown"}),
        "dead_urls": sorted({h["url"] for h in url_hits if h.get("link_status") == "dead"}),
    }
    if scope is not None:
        out["out_of_vocab"] = sorted({h["cite"] for h in hits
                                      if h["resolves"] and not h.get("in_vocab")})
    return out
