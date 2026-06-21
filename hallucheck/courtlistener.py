"""CourtListener (Free Law Project) lookup — pull the *real* opinion for a cite.

Opt-in network enrichment for case citations: resolve a cite to its CourtListener
opinion (free, no key required for the search API; a ``COURTLISTENER_TOKEN`` only
raises rate limits), so a verification packet can link straight to the opinion
page and, when available, its downloadable file — moving an attorney from "here is
a holding summary" to "here is the opinion."

Network is **never** used unless a caller opts in, and every call is wrapped so a
failure degrades to ``{"found": False, "error": ...}`` rather than raising — the
packet must still build offline. The HTTP layer is injectable (``http=``) so the
behavior is tested deterministically without a network. As everywhere in this
project: a returned link is a *starting point for review*, not a verified match —
confirm the opinion is the right one and is still good law.
"""
from __future__ import annotations

import ipaddress
import json
import socket
import urllib.request
from urllib.parse import urlencode, urlparse

from .links import USER_AGENT

BASE = "https://www.courtlistener.com"
STORAGE = "https://storage.courtlistener.com/"
SEARCH = BASE + "/api/rest/v4/search/"
OPINION = BASE + "/api/rest/v4/opinions/{id}/"

# Resource caps (defensive: a hostile/oversized response shouldn't exhaust us).
MAX_JSON_BYTES = 8 * 1024 * 1024
MAX_FILE_BYTES = 40 * 1024 * 1024


def _assert_fetchable(url: str) -> None:
    """SSRF guard for downloads: allow only http(s) to a publicly-routable host.

    Blocks ``file://`` / ``ftp://`` / ``data:`` and URLs that resolve to private,
    loopback, link-local (incl. the cloud metadata 169.254.169.254), reserved or
    multicast addresses. (Residual: DNS rebinding between this check and the
    connect — acceptable for an opt-in research download.)"""
    p = urlparse(url)
    if p.scheme not in ("http", "https"):
        raise ValueError(f"refusing non-http(s) URL: {url!r}")
    host = p.hostname
    if not host:
        raise ValueError(f"no host in URL: {url!r}")
    try:
        infos = socket.getaddrinfo(host, p.port or (443 if p.scheme == "https" else 80),
                                   proto=socket.IPPROTO_TCP)
    except OSError as e:
        raise ValueError(f"cannot resolve host {host!r}: {e}") from e
    for *_, sockaddr in infos:
        ip = ipaddress.ip_address(sockaddr[0])
        if (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved
                or ip.is_multicast or ip.is_unspecified):
            raise ValueError(f"refusing URL resolving to non-public address {ip} ({host})")


def _http(url: str, *, timeout: int = 20, token: str | None = None) -> str:
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Token {token}"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read(MAX_JSON_BYTES + 1)
    if len(raw) > MAX_JSON_BYTES:
        raise ValueError("CourtListener response exceeds size cap")
    return raw.decode("utf-8", "replace")


def lookup(cite: str, *, timeout: int = 20, token: str | None = None, http=None) -> dict:
    """Resolve a case ``cite`` to its CourtListener opinion via the search API.

    Returns ``{found, cite, case_name, court, date, citations, cluster_id,
    opinion_id, absolute_url, download_url, snippet}`` (``found: False`` with an
    ``error`` on any failure — never raises). Prefers an exact citation match."""
    http = http or _http
    params = urlencode({"q": f'"{cite}"', "type": "o"})
    try:
        data = json.loads(http(f"{SEARCH}?{params}", timeout=timeout, token=token))
    except Exception as e:                                # noqa: BLE001
        return {"found": False, "cite": cite, "error": f"{type(e).__name__}: {e}"}

    results = data.get("results") or []
    best = next((r for r in results if cite in (r.get("citation") or [])), None)
    best = best or (results[0] if results else None)
    if not best:
        return {"found": False, "cite": cite}

    op = (best.get("opinions") or [{}])[0]
    rel = best.get("absolute_url") or ""
    return {
        "found": True, "cite": cite,
        "case_name": best.get("caseName"),
        "court": best.get("court"),
        "date": best.get("dateFiled"),
        "citations": best.get("citation") or [],
        "cite_count": best.get("citeCount"),             # later citations (treatment lead)
        "cluster_id": best.get("cluster_id"),
        "opinion_id": op.get("id"),
        "absolute_url": (BASE + rel) if rel else None,
        "download_url": op.get("download_url"),          # original court file (often null)
        "snippet": (op.get("snippet") or "").strip() or None,
    }


def citing(opinion_id, *, limit: int = 5, timeout: int = 20, token: str | None = None,
           http=None) -> dict:
    """Later opinions that cite ``opinion_id``, most-recent first — the references
    an attorney reviews for negative treatment.

    Uses the free, anonymous search filter ``q=cites:(<id>)``. Returns
    ``{count, opinions:[{case_name, court, date, citations, absolute_url}],
    search_url}`` (truncated to ``limit``); ``{count:0, opinions:[], error}`` on
    failure. This lists *who cites the case*, NOT whether the treatment is
    negative — that judgment is the attorney's."""
    http = http or _http
    params = urlencode({"q": f"cites:({opinion_id})", "type": "o",
                        "order_by": "dateFiled desc"})
    try:
        data = json.loads(http(f"{SEARCH}?{params}", timeout=timeout, token=token))
    except Exception as e:                                # noqa: BLE001
        return {"count": 0, "opinions": [], "error": f"{type(e).__name__}: {e}"}
    out = []
    for r in (data.get("results") or [])[:max(0, limit)]:
        rel = r.get("absolute_url") or ""
        out.append({"case_name": r.get("caseName"), "court": r.get("court"),
                    "date": r.get("dateFiled"), "citations": r.get("citation") or [],
                    "absolute_url": (BASE + rel) if rel else None})
    return {"count": data.get("count"), "opinions": out,
            "search_url": f"{BASE}/?q=cites:({opinion_id})&type=o&order_by=dateFiled+desc"}


def opinion(opinion_id, *, timeout: int = 20, token: str | None = None, http=None) -> dict:
    """Fetch one opinion's detail: ``{plain_text, download_url, local_path,
    file_url}``. ``file_url`` is the best downloadable file (original court URL, or
    CourtListener's stored copy). ``{}`` on failure."""
    http = http or _http
    try:
        d = json.loads(http(OPINION.format(id=opinion_id), timeout=timeout, token=token))
    except Exception:                                    # noqa: BLE001
        return {}
    local = d.get("local_path")
    file_url = d.get("download_url") or (STORAGE + local if local else None)
    return {"plain_text": d.get("plain_text") or None,
            "download_url": d.get("download_url"),
            "local_path": local, "file_url": file_url}


def fetch_file(url: str, dest, *, timeout: int = 30, token: str | None = None,
               max_bytes: int = MAX_FILE_BYTES) -> str:
    """Download an opinion file to ``dest``. Returns the path. Validates the URL
    (http(s), public host — see :func:`_assert_fetchable`) and caps the size;
    raises on any failure (callers that must stay offline-safe should guard it)."""
    import pathlib
    _assert_fetchable(url)
    headers = {"User-Agent": USER_AGENT}
    if token:
        headers["Authorization"] = f"Token {token}"
    req = urllib.request.Request(url, headers=headers)
    p = pathlib.Path(dest)
    p.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    with urllib.request.urlopen(req, timeout=timeout) as r, p.open("wb") as fh:
        while True:
            chunk = r.read(65536)
            if not chunk:
                break
            written += len(chunk)
            if written > max_bytes:
                fh.close()
                p.unlink(missing_ok=True)
                raise ValueError(f"opinion file exceeds size cap ({max_bytes} bytes)")
            fh.write(chunk)
    return str(p)


def enrich(entry: dict, *, token: str | None = None, http=None,
           timeout: int = 20, citing_limit: int = 0) -> dict:
    """Attach a CourtListener result to a packet *case* entry: sets
    ``entry['courtlistener']`` and appends opinion / download links to
    ``entry['sources']['links']``. With ``citing_limit > 0``, also attaches the
    most-recent citing opinions (``res['citing']``) for treatment review. No-op
    (returns entry) for non-cases."""
    if entry.get("kind") != "case":
        return entry
    res = lookup(entry["cite"], token=token, http=http, timeout=timeout)
    entry["courtlistener"] = res
    if res.get("found") and res.get("absolute_url"):
        links = entry["sources"]["links"]
        links.append({"provider": "courtlistener_opinion",
                      "label": "CourtListener — full opinion", "access": "free",
                      "url": res["absolute_url"]})
        if res.get("download_url"):
            links.append({"provider": "courtlistener_pdf",
                          "label": "CourtListener — opinion file", "access": "free",
                          "url": res["download_url"]})
        if citing_limit and res.get("opinion_id"):
            res["citing"] = citing(res["opinion_id"], limit=citing_limit,
                                   token=token, http=http, timeout=timeout)
    return entry
