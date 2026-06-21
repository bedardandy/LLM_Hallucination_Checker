"""Citation verification packets — the attorney-review / Shepardize workbench.

Turn a set of citations (or the citations found in a brief) into a structured
*verification packet*: for each authority, the real source text (proof it exists
and says what it says), a SHA-256 of that text, links to read and verify it
across services (:mod:`hallucheck.sources`), a slot to record treatment (the
attorney's Shepardize result), and cross-links to related authorities already in
the packet. :mod:`hallucheck.embed` renders the packet to Markdown / HTML and
(optionally) DOCX / PDF with internal bookmarks, so a brief's citation can jump
to a bookmarked section showing the authority's text and any noted treatment.

What it does **not** do: decide whether a case is still good law. Negative
treatment cannot be derived from a closed corpus; this assembles everything a
licensed attorney needs to make that determination by hand, and records the
attorney's findings (``treatments``) as first-class, cross-linked entries.
"""
from __future__ import annotations

import datetime

from . import attest, courtlistener, sources
from .disclaimer import LIBRARY_DISCLAIMER, combined
from .textnorm import clean

SCHEMA = "hallucheck-verification-packet/v1"


def anchor(cite: str) -> str:
    """Stable, file-name-safe id for a citation (HTML anchor / DOCX bookmark /
    PDF outline key)."""
    safe = "".join(c if c.isalnum() else "-" for c in (cite or "")).strip("-")
    while "--" in safe:
        safe = safe.replace("--", "-")
    return "auth-" + (safe.lower() or "x")


def extract_cites(adapter, draft: str, *, scope: str | None = None) -> list[dict]:
    """Distinct citations found in ``draft`` (deterministic, offline). Each:
    ``{cite, kind, resolves, in_vocab?}`` — order of first appearance."""
    seen: dict[str, dict] = {}
    for h in adapter.citation_spans(clean(draft or ""), scope=scope):
        rec = seen.setdefault(h["cite"], {"cite": h["cite"], "kind": h.get("kind"),
                                          "resolves": h.get("resolves", False)})
        if "in_vocab" in h:
            rec["in_vocab"] = h["in_vocab"]
        rec["resolves"] = rec["resolves"] or h.get("resolves", False)
    return list(seen.values())


def _treatment(cite: str, treatments: dict | None) -> dict:
    base = {"status": "unreviewed", "note": "", "authorities": [], "reviewed_by": None}
    if treatments and cite in treatments:
        t = treatments[cite] or {}
        base.update({k: t[k] for k in ("status", "note", "authorities", "reviewed_by")
                     if k in t})
    return base


def _entry(adapter, cite: str, meta: dict, *, fetch_text: bool,
           treatments: dict | None) -> dict:
    title = meta.get("title") or meta.get("name")
    url = meta.get("url")
    kind = meta.get("kind")
    text, dead, ok = None, False, False
    try:
        resolved = adapter.resolve(cite, fetch_text=fetch_text)
    except Exception as exc:                       # never let one cite break the packet
        resolved = None
        meta = {**meta, "resolve_error": f"{type(exc).__name__}: {exc}"}
    if resolved:
        url = resolved.get("url") or url
        title = resolved.get("title") or title
        if resolved.get("dead_link"):
            dead = True
        elif resolved.get("text"):
            text, ok = resolved["text"], True

    rec = {"cite": cite, "kind": kind, "title": title, "url": url, "name": meta.get("name")}
    return {
        "cite": cite,
        "kind": sources.for_citation(rec)["kind"],
        "title": title,
        "url": url,
        "resolved": ok,
        "dead_link": dead,
        "in_vocab": meta.get("in_vocab"),
        "text": text,
        "text_sha256": attest.sha256_text(text) if text else None,
        "sources": sources.for_citation(rec),
        "treatment": _treatment(cite, treatments),
        "related": [],
        "anchor": anchor(cite),
        "note": meta.get("resolve_error"),
    }


def _relate(entries: list[dict]) -> None:
    """Cross-link authorities that reference one another: if entry B's cite string
    appears in entry A's text (e.g. a case holding that names the statute it
    construes), link A<->B. Bidirectional, deduplicated, sorted."""
    by_cite = {e["cite"]: e for e in entries}
    rel: dict[str, set] = {e["cite"]: set() for e in entries}
    for a in entries:
        hay = (a.get("text") or "")
        if not hay:
            continue
        for cite_b, b in by_cite.items():
            if cite_b == a["cite"]:
                continue
            if cite_b in hay:
                rel[a["cite"]].add(cite_b)
                rel[cite_b].add(a["cite"])
    for e in entries:
        e["related"] = [
            {"cite": c, "kind": by_cite[c]["kind"], "title": by_cite[c]["title"],
             "anchor": by_cite[c]["anchor"]}
            for c in sorted(rel[e["cite"]])]


def build_packet(adapter, *, cites: list[str] | None = None, draft: str | None = None,
                 scope: str | None = None, fetch_text: bool = True,
                 treatments: dict | None = None, title: str | None = None,
                 courtlistener_lookup: bool = False, cl_token: str | None = None,
                 cl_http=None, cl_timeout: int = 20, cl_citing_limit: int = 0) -> dict:
    """Build a verification packet from an explicit ``cites`` list and/or the
    citations found in ``draft``. ``fetch_text=False`` keeps it fully offline
    (uses the adapter's offline authority text). ``treatments`` maps a cite to an
    attorney-recorded ``{status, note, authorities:[{cite|url,label}]}``.

    ``courtlistener_lookup=True`` opts into a network call per case citation to
    attach the CourtListener opinion link/excerpt (``cl_token`` raises rate
    limits; ``cl_http`` injects the HTTP layer for tests). ``cl_citing_limit > 0``
    also attaches the most-recent citing opinions per case for treatment review."""
    vocab = {}
    try:
        vocab = adapter.build_vocabulary(scope)
    except Exception:
        vocab = {}

    found = extract_cites(adapter, draft, scope=scope) if draft else []
    order: list[str] = []
    metas: dict[str, dict] = {}
    for src in (found, [{"cite": c} for c in (cites or [])]):
        for rec in src:
            c = rec["cite"]
            if c not in metas:
                order.append(c)
                metas[c] = {}
            v = vocab.get(c, {})
            metas[c].update({k: v.get(k) for k in ("kind", "title", "url", "name") if v.get(k)})
            for k in ("kind", "in_vocab"):
                if rec.get(k) is not None:
                    metas[c].setdefault(k, rec[k])

    entries = [_entry(adapter, c, metas[c], fetch_text=fetch_text, treatments=treatments)
               for c in order]
    _relate(entries)

    # A treatment can cite another authority in the packet (e.g. the case that
    # gives this one negative treatment); link those to its section so the chain
    # is followable in the rendered document.
    by_cite = {e["cite"]: e for e in entries}
    for e in entries:
        for a in e["treatment"].get("authorities", []):
            if a.get("cite") in by_cite and not a.get("anchor"):
                a["anchor"] = by_cite[a["cite"]]["anchor"]

    if courtlistener_lookup:
        for e in entries:
            courtlistener.enrich(e, token=cl_token, http=cl_http, timeout=cl_timeout,
                                 citing_limit=cl_citing_limit)

    counts = {
        "total": len(entries),
        "resolved": sum(1 for e in entries if e["resolved"]),
        "unresolved": sum(1 for e in entries if not e["resolved"] and not e["dead_link"]),
        "dead_links": sum(1 for e in entries if e["dead_link"]),
        "treated": sum(1 for e in entries if e["treatment"]["status"] != "unreviewed"),
        "courtlistener": sum(1 for e in entries
                             if (e.get("courtlistener") or {}).get("found")),
    }
    return {
        "schema": SCHEMA,
        "tool": "hallucheck",
        "adapter": getattr(adapter, "name", None),
        "scope": scope,
        "title": title or "Citation Verification Packet",
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "config_digest": _safe_digest(adapter),
        "library_disclaimer": LIBRARY_DISCLAIMER,
        "disclaimer": combined(getattr(adapter, "disclaimer", None)),
        "from_draft": bool(draft),
        "counts": counts,
        "unverified": sorted(e["cite"] for e in entries if not e["resolved"]),
        "entries": entries,
    }


def attach_opinions(packet: dict, dest_dir, *, token: str | None = None,
                    http=None, fetch=None) -> int:
    """Download the available opinion file for each CourtListener-resolved case
    entry into ``dest_dir`` and add a local link. Network; requires a packet built
    with ``courtlistener_lookup=True``. Returns the number of files saved; never
    raises (a failed download just adds no local link). ``http``/``fetch`` are
    injectable for tests."""
    import pathlib
    fetch = fetch or courtlistener.fetch_file
    dest = pathlib.Path(dest_dir)
    saved = 0
    for e in packet.get("entries", []):
        cl = e.get("courtlistener") or {}
        if not (cl.get("found") and cl.get("opinion_id")):
            continue
        try:
            det = courtlistener.opinion(cl["opinion_id"], token=token, http=http)
            file_url = det.get("file_url")
            if not file_url:
                continue
            ext = pathlib.Path(file_url.split("?")[0]).suffix or ".pdf"
            out = dest / f"{e['anchor']}{ext}"
            fetch(file_url, str(out), token=token)
            e["sources"]["links"].append(
                {"provider": "local_opinion_file", "access": "free",
                 "label": "Downloaded opinion file", "url": str(out)})
            saved += 1
        except Exception:                                # noqa: BLE001
            continue
    return saved


def _safe_digest(adapter):
    try:
        return adapter.config_digest()
    except Exception:
        return None
