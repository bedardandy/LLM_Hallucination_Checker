"""Open-vocabulary case-law adapter backed by CourtListener.

Unlike the Maine adapter (a *closed* bundled statute index), this recognizes
case-citation surface forms and uses CourtListener as the resolver/index — so it
works for **any jurisdiction's case law** without a local corpus.

The trade-off is explicit and important: the **closed-vocabulary guarantee is
relaxed**. The ``[[REF:]]`` protocol still forces the model to cite only the KEYs
you seed via ``scope`` (each confirmed to resolve in CourtListener), but the
universe of valid citations is no longer a fixed allow-list you control. Offline,
citation *existence* cannot be proven, so for this adapter the scanner's value is
the leaked-cite (out-of-protocol) net and URL checks; **resolvability is confirmed
at ``resolve()``-time over the network**, not in the offline scan. Treat a
resolved opinion as a lead to read, not a verified match — and, as always, not
legal advice.
"""
from __future__ import annotations

import os
import re

from hallucheck import courtlistener as _cl
from hallucheck.textnorm import clean

DISCLAIMER = (
    "EXPERIMENTAL — open-vocabulary case-law lookup via CourtListener (a free "
    "third-party database). This does NOT enforce a closed citation allow-list: a "
    "citation 'resolves' only if CourtListener returns a match, which can be the "
    "wrong, superseded, or an unrelated case. Not legal advice; a licensed attorney "
    "must read each opinion and confirm it is on point and still good law.")

# Reporter and vendor-neutral case-citation surface forms (broad, multi-state).
_REPORTER = (r"A\.?\s?[23]d|U\.?\s?S\.?|S\.?\s?Ct\.?|L\.?\s?Ed\.?\s?2d|F\.?\s?[234]d|"
             r"F\.?\s?Supp\.?\s?[23]?d?|P\.?\s?[23]d|N\.?E\.?\s?[23]d|N\.?W\.?\s?[23]d|"
             r"S\.?E\.?\s?[23]d|S\.?W\.?\s?[23]d|So\.?\s?[23]d|Cal\.?\s?Rptr\.?\s?[23]d?")
_RE_REPORTER = re.compile(rf"\b(\d+)\s+({_REPORTER})\s+(\d+)\b")
_RE_NEUTRAL = re.compile(r"\b(\d{4})\s+([A-Z]{2,5})\s+(\d+)\b")


def _canon(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


class CourtListenerCaselawAdapter:
    name = "courtlistener"
    disclaimer = DISCLAIMER

    def __init__(self, *, http=None, token: str | None = None):
        self._http = http
        self._token = token or os.environ.get("COURTLISTENER_TOKEN")
        self._cache: dict[str, dict | None] = {}

    # --- scope parsing ------------------------------------------------------ #
    def _scope_cites(self, scope) -> list[str]:
        """``scope`` may be a list of cites, a path to a file (one cite per line),
        or a ``;`` / newline-separated string. ``None`` -> no seed vocabulary."""
        if scope is None:
            return []
        if isinstance(scope, (list, tuple)):
            return [_canon(c) for c in scope if _canon(c)]
        try:
            import pathlib
            p = pathlib.Path(scope)
            if p.exists():
                scope = p.read_text(encoding="utf-8")
        except (OSError, ValueError):
            pass
        return [_canon(c) for c in re.split(r"[;\n]", str(scope)) if _canon(c)]

    # --- resolution (network) ---------------------------------------------- #
    def resolve(self, key: str, *, fetch_text: bool = True) -> dict | None:
        key = _canon(key)
        if key in self._cache:
            return self._cache[key]
        res = _cl.lookup(key, token=self._token, http=self._http)
        out = None
        if res.get("found"):
            text = None
            if fetch_text:
                if self._token and res.get("opinion_id"):
                    text = _cl.opinion(res["opinion_id"], token=self._token,
                                       http=self._http).get("plain_text")
                text = text or res.get("snippet")
            text = text or (f"{res.get('case_name')} ({key}) — {res.get('court')}, "
                            f"{res.get('date')}")
            out = {"cite": key, "title": res.get("case_name"),
                   "url": res.get("absolute_url"), "text": text}
        self._cache[key] = out
        return out

    # --- vocabulary (network: confirms each seed resolves) ------------------ #
    def build_vocabulary(self, scope=None) -> dict:
        vocab: dict[str, dict] = {}
        for cite in self._scope_cites(scope):
            r = self.resolve(cite, fetch_text=False)
            if r:
                vocab[cite] = {"kind": "case", "cite": cite,
                               "title": r.get("title"), "url": r.get("url")}
        return vocab

    # --- deterministic scanner (offline) ----------------------------------- #
    def citation_spans(self, text: str, *, scope=None) -> list[dict]:
        text = clean(text or "")
        vocab = set(self.build_vocabulary(scope)) if scope else None
        hits: list = []
        taken: list = []

        def add(s, e, raw, cite):
            if any(not (e <= ts or s >= te) for ts, te in taken):
                return
            taken.append((s, e))
            # Open corpus: a well-formed case cite is treated as resolvable; actual
            # existence is confirmed at resolve()-time, not offline.
            rec = {"raw": raw.strip(), "cite": cite, "kind": "case",
                   "span": [s, e], "resolves": True}
            if vocab is not None:
                rec["in_vocab"] = cite in vocab
            hits.append(rec)

        for m in _RE_REPORTER.finditer(text):
            add(m.start(), m.end(), m.group(0),
                _canon(f"{m.group(1)} {m.group(2)} {m.group(3)}"))
        for m in _RE_NEUTRAL.finditer(text):
            add(m.start(), m.end(), m.group(0),
                _canon(f"{m.group(1)} {m.group(2)} {m.group(3)}"))
        hits.sort(key=lambda h: h["span"][0])
        return hits

    # --- URLs --------------------------------------------------------------- #
    def url_in_index(self, url: str) -> bool | None:
        if not url:
            return None
        return True if "courtlistener.com" in url else None

    def index_urls(self, scope="used") -> dict:
        urls: dict[str, list] = {}
        for cite, m in self.build_vocabulary(scope if scope != "used" else None).items():
            if m.get("url"):
                urls.setdefault(m["url"], []).append(cite)
        return urls

    def config_digest(self) -> str:
        return "courtlistener-open/v1"
