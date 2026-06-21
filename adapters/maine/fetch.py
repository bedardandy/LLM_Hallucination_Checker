"""Live statute-text fetch for legislature.maine.gov (host-specific).

legislature.maine.gov returns 403 to non-browser User-Agents, so we send a
browser-like UA. On failure we classify the link (DEAD vs BLOCKED) using
``hallucheck.links.classify_status`` so the inspector can flag a dead authority
URL distinctly from a merely blocked one. HTML is not byte-stable, so we extract
and normalize the section body in one quarantined function.
"""
from __future__ import annotations

import html as _html
import re
import socket
import urllib.error
import urllib.request
from html.parser import HTMLParser

from hallucheck.links import classify_status

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
_HEADERS = {"User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9"}


class _TextExtractor(HTMLParser):
    _SKIP = {"script", "style", "head", "nav", "header", "footer", "noscript",
             "form", "button", "select"}
    _BREAK = {"br", "p", "div", "li", "tr", "h1", "h2", "h3", "h4"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self._skip, self._chunks = 0, []

    def handle_starttag(self, tag, attrs):
        if tag in self._SKIP:
            self._skip += 1
        elif self._skip == 0 and tag in self._BREAK:
            self._chunks.append("\n")

    def handle_endtag(self, tag):
        if tag in self._SKIP and self._skip:
            self._skip -= 1
        elif self._skip == 0 and tag in self._BREAK:
            self._chunks.append("\n")

    def handle_data(self, data):
        if self._skip == 0:
            self._chunks.append(data)

    def text(self):
        return "".join(self._chunks)


def _normalize(text: str) -> str:
    text = _html.unescape(text)
    for ws in (" ", " ", " ", "​"):
        text = text.replace(ws, " ")
    lines = [re.sub(r"[ \t]+", " ", ln).strip() for ln in text.splitlines()]
    return "\n".join(ln for ln in lines if ln)


def _section_token(cite: str) -> str | None:
    m = re.search(r"§\s*([0-9A-Za-z\-]+)", cite or "")
    return m.group(1) if m else None


def extract_statute_text(html_text: str, cite: str) -> str:
    parser = _TextExtractor()
    parser.feed(html_text or "")
    body = _normalize(parser.text())
    sec = _section_token(cite)
    if not sec:
        return body
    start = re.search(r"§\s*" + re.escape(sec) + r"\b", body)
    if not start:
        return body
    tail = body[start.start():]
    end = len(tail)
    nxt = re.search(r"\n[^\n]*§\s*(?!" + re.escape(sec) + r"\b)[0-9]", tail)
    if nxt:
        end = nxt.start()
    for marker in ("The Revisor's Office", "Office of the Revisor",
                   "This page is maintained", "Data for this page"):
        fi = tail.find(marker)
        if 0 < fi < end:
            end = fi
    return tail[:end].strip()


def _download(url: str, timeout: int = 60) -> str:
    req = urllib.request.Request(url, headers=_HEADERS)
    return urllib.request.urlopen(req, timeout=timeout).read().decode("utf-8", "replace")


def _link_status(exc: Exception) -> str:
    if isinstance(exc, urllib.error.HTTPError):
        return classify_status(exc.code)
    if isinstance(exc, urllib.error.URLError) and isinstance(
            getattr(exc, "reason", None), socket.gaierror):
        return "dead"
    return "inconclusive"


def fetch_statute_text(cite: str, url: str, *, timeout: int = 60,
                       downloader=None) -> dict:
    """Return ``{cite, url, text, link_status}``. On failure ``text`` is None and
    ``link_status`` is dead/blocked/inconclusive."""
    dl = downloader or _download
    try:
        html_text = dl(url, timeout=timeout)
    except Exception as e:
        return {"cite": cite, "url": url, "text": None,
                "link_status": _link_status(e), "error": str(e)}
    return {"cite": cite, "url": url, "text": extract_statute_text(html_text, cite),
            "link_status": "live"}
