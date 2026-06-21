"""Maine probate corpus adapter — a complete reference implementation.

Implements ``hallucheck.adapter.Adapter`` over the bundled Maine Uniform Probate
Code index (Title 18-C sections, Law Court cases, non-18-C cross-refs) and a few
example per-form vocabularies. Statute text is fetched live from
legislature.maine.gov; case "text" is the summarized holding.

In a host repo (e.g. maine-probate-forms) you would subclass this to read that
repo's full per-form ``statutes.json`` instead of the bundled examples — the
protocol is identical. Not legal advice; experimental, AI-annotated.
"""
from __future__ import annotations

import functools
import hashlib
import json
import pathlib
import re
from typing import Optional

from hallucheck.textnorm import clean

from . import fetch

DATA = pathlib.Path(__file__).resolve().parent / "data"

DISCLAIMER = (
    "EXPERIMENTAL — AI/LLM-GENERATED, NOT ATTORNEY-REVIEWED. For consideration "
    "only; NOT legal advice. Statute titles/text are from legislature.maine.gov, "
    "but the SELECTION of authorities and any holdings are model annotations and "
    "may be wrong. Verify against the current statute and the actual opinions.")

# --- citation surface forms (Maine) ---------------------------------------- #
_RE_18C = re.compile(r"\b18-C\b\s*(?:M\.?\s?R\.?\s?S\.?(?:A\.?)?)?[,\s]*"
                     r"(?:§|sec(?:tion|\.)?)\s*(\d+-\d+)(?:\([0-9A-Za-z]+\))?", re.IGNORECASE)
# Spelled-out reverse order: "Section 9-999 of Title 18-C", "§3-401 of 18-C".
_RE_18C_REV = re.compile(r"(?:§|sec(?:tion|\.)?)\s*(\d+-\d+)(?:\([0-9A-Za-z]+\))?"
                         r"\s+of\s+(?:Title\s+)?18-C\b", re.IGNORECASE)
_RE_MRS = re.compile(r"\b(\d+(?:-[A-Z])?)\s*M\.?\s?R\.?\s?S\.?(?:A\.?)?\s*"
                     r"(?:§\s*(\d+(?:-[A-Z])?)(?:\([0-9A-Za-z]+\))?)?")
_RE_ME = re.compile(r"\b(\d{4})\s+ME\s+(\d+)\b")
_RE_ATL = re.compile(r"\b(\d+)\s+A\.?\s?([23])d\s+(\d+)\b")
_RE_BARE = re.compile(r"§\s*(\d+-\d+)(?:\([0-9A-Za-z]+\))?")
# Enumerated list after §/§§: "§§ 3-401, 3-203 and 9-999" -> each section.
_RE_SECLIST = re.compile(r"§§?\s*\d+-\d+(?:\s*(?:,|;|and|&)\s*\d+-\d+)+")
_RE_SUBSEC = re.compile(r"\([0-9A-Za-z]+\)\s*$")
_RE_18C_URL = re.compile(r"title18-Csec([0-9A-Za-z\-]+)\.html", re.IGNORECASE)
_RE_MRS_URL = re.compile(r"/statutes/(\d+(?:-[A-Z])?)/title[^/]*sec([0-9A-Za-z\-]+)\.html",
                         re.IGNORECASE)


def _name_variants(name: str):
    out = {name}
    m = re.match(r"(?i)in re\s+", name)
    if m:
        out.add(name[m.end():])
    return out


class MaineProbateAdapter:
    name = "maine"
    disclaimer = DISCLAIMER

    @functools.cached_property
    def _sections(self):
        return json.loads((DATA / "18c-sections.json").read_text(encoding="utf-8"))["sections"]

    @functools.cached_property
    def _xref(self):
        return json.loads((DATA / "cross-refs.json").read_text(encoding="utf-8"))["cross_refs"]

    @functools.cached_property
    def _cases(self):
        return json.loads((DATA / "caselaw.json").read_text(encoding="utf-8"))["cases"]

    @functools.cached_property
    def _case_by_cite(self):
        return {c["cite"]: c for c in self._cases.values()}

    def _section_of(self, cite: str) -> Optional[str]:
        """Section key for an 18-C cite, tolerating a trailing subsection
        (``18-C §3-401(a)`` -> ``3-401``)."""
        if cite.startswith("18-C §"):
            return _RE_SUBSEC.sub("", cite[len("18-C §"):]).strip()
        return None

    def _resolves(self, cite: str) -> bool:
        if cite in self._xref:
            return True
        sec = self._section_of(cite)
        if sec is not None:
            return sec in self._sections
        return cite in self._case_by_cite

    # --- vocabulary --------------------------------------------------------- #
    def build_vocabulary(self, scope: str | None = None) -> dict:
        vocab: dict[str, dict] = {}

        def add_statute(cite, title=None, url=None, note=None):
            if not cite or cite in vocab:
                return
            if cite in self._xref:
                m = self._xref[cite]
                vocab[cite] = {"kind": "crossref", "cite": cite, "title": title or m.get("title"),
                               "url": url or m.get("url"), "note": note or m.get("note")}
            elif cite.startswith("18-C §") and cite[len("18-C §"):] in self._sections:
                m = self._sections[cite[len("18-C §"):]]
                vocab[cite] = {"kind": "statute", "cite": cite, "title": title or m.get("title"),
                               "url": url or m.get("url"), "note": note}

        def add_case(cite):
            c = self._case_by_cite.get(cite)
            if c and cite not in vocab:
                vocab[cite] = {"kind": "case", "cite": cite, "title": c.get("name"),
                               "url": c.get("url"), "holding": c.get("holding")}

        form = self._form(scope) if scope else None
        if form is not None:
            for g in form.get("governing", []):
                add_statute(g.get("cite"), g.get("title"), g.get("url"), g.get("why"))
            for pq in form.get("per_question", []):
                for c in pq.get("considerations", []):
                    add_statute(c.get("cite"), c.get("title"), c.get("url"), c.get("note"))
            for x in form.get("cross_refs", []):
                add_statute(x.get("cite"), x.get("title"), x.get("url"))
            for c in form.get("caselaw", []):
                add_case(c.get("cite"))
        else:                                  # whole index
            for sec in self._sections:
                add_statute(f"18-C §{sec}")
            for cite in self._xref:
                add_statute(cite)
            for cite in self._case_by_cite:
                add_case(cite)
        return vocab

    def _form(self, scope: str) -> Optional[dict]:
        p = DATA / "forms" / f"{scope}.json"
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None

    # --- resolution --------------------------------------------------------- #
    def resolve(self, key: str, *, fetch_text: bool = True) -> Optional[dict]:
        sec = self._section_of(key)
        if key in self._xref or (sec is not None and sec in self._sections):
            meta = self._xref.get(key) or self._sections.get(sec, {})
            url, title = meta.get("url"), meta.get("title")
            if fetch_text and url:
                res = fetch.fetch_statute_text(key, url)
                if res.get("text"):
                    return {"cite": key, "title": title, "url": url, "text": res["text"]}
                if res.get("link_status") == "dead":
                    return {"cite": key, "title": title, "url": url,
                            "text": None, "dead_link": True}
                return None
            parts = [title or key]
            if meta.get("note"):
                parts.append(meta["note"])
            return {"cite": key, "title": title, "url": url, "text": "\n".join(parts)}
        c = self._case_by_cite.get(key)
        if c and c.get("holding"):
            return {"cite": key, "title": c.get("name"), "url": c.get("url"),
                    "text": f"{c.get('name')} ({key}). Holding (summarized): {c['holding']}"}
        return None

    def draft_system_prompt(self, scope: str | None = None) -> str:
        from hallucheck.inspector import draft_system_prompt
        return draft_system_prompt(self.build_vocabulary(scope))

    # --- deterministic scanner --------------------------------------------- #
    def citation_spans(self, text: str, *, scope: str | None = None) -> list[dict]:
        text = clean(text or "")          # fold homoglyphs / strip zero-width (idempotent)
        vocab = set(self.build_vocabulary(scope)) if scope else None
        hits, taken = [], []

        def add(s, e, raw, cite, kind):
            if any(not (e <= ts or s >= te) for ts, te in taken):
                return
            taken.append((s, e))
            rec = {"raw": raw.strip(), "cite": cite, "kind": kind, "span": [s, e],
                   "resolves": self._resolves(cite)}
            if vocab is not None:
                rec["in_vocab"] = cite in vocab
            hits.append(rec)

        for m in _RE_18C.finditer(text):
            add(m.start(), m.end(), m.group(0), f"18-C §{m.group(1)}", "statute")
        for m in _RE_18C_REV.finditer(text):
            add(m.start(), m.end(), m.group(0), f"18-C §{m.group(1)}", "statute")
        for m in _RE_ME.finditer(text):
            add(m.start(), m.end(), m.group(0), f"{m.group(1)} ME {m.group(2)}", "case")
        for m in _RE_ATL.finditer(text):
            add(m.start(), m.end(), m.group(0), f"{m.group(1)} A.{m.group(2)}d {m.group(3)}", "case")
        for m in _RE_MRS.finditer(text):
            if m.group(1) == "18-C":
                continue
            cite = f"{m.group(1)} M.R.S. §{m.group(2)}" if m.group(2) else f"{m.group(1)} M.R.S."
            add(m.start(), m.end(), m.group(0), cite, "crossref")
        for m in _RE_SECLIST.finditer(text):        # "§§ 3-401, 9-999" -> each item
            for sub in re.finditer(r"\d+-\d+", m.group(0)):
                add(m.start() + sub.start(), m.start() + sub.end(),
                    sub.group(0), f"18-C §{sub.group(0)}", "statute")
        for m in _RE_BARE.finditer(text):
            add(m.start(), m.end(), m.group(0), f"18-C §{m.group(1)}", "statute")
        for c in self._cases.values():
            if not c.get("name"):
                continue
            for variant in _name_variants(c["name"]):
                for m in re.finditer(re.escape(variant), text, re.IGNORECASE):
                    add(m.start(), m.end(), m.group(0), c["cite"], "case")
        hits.sort(key=lambda h: h["span"][0])
        return hits

    # --- URLs --------------------------------------------------------------- #
    @functools.cached_property
    def _all_urls(self):
        urls = set()
        for blob in (self._sections, self._xref, self._cases):
            for m in blob.values():
                if m.get("url"):
                    urls.add(m["url"])
        return urls

    def url_in_index(self, url: str) -> Optional[bool]:
        if not url or "legislature.maine.gov" not in url:
            return None
        if url in self._all_urls:
            return True
        m = _RE_18C_URL.search(url)
        if m:
            return m.group(1) in self._sections
        m2 = _RE_MRS_URL.search(url)
        if m2:
            return f"{m2.group(1)} M.R.S. §{m2.group(2)}" in self._xref
        return None

    def index_urls(self, scope: str = "used") -> dict:
        urls: dict[str, set] = {}

        def add(url, cite):
            if url:
                urls.setdefault(url, set()).add(cite)

        if scope == "all":
            for sec, m in self._sections.items():
                add(m.get("url"), f"18-C §{sec}")
        else:                                  # used: bundled example forms' cites
            for vocab in (self.build_vocabulary(p.stem) for p in (DATA / "forms").glob("*.json")):
                for cite, m in vocab.items():
                    add(m.get("url"), cite)
        for cite, m in self._xref.items():
            add(m.get("url"), cite)
        for cid, m in self._cases.items():
            add(m.get("url"), m.get("cite", cid))
        return {u: sorted(c) for u, c in urls.items()}

    def config_digest(self) -> str:
        h = hashlib.sha256()
        for name in ("18c-sections.json", "caselaw.json", "cross-refs.json"):
            h.update((DATA / name).read_bytes())
        return h.hexdigest()[:16]
