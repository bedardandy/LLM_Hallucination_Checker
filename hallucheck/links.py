"""Dead-link detection (stdlib only).

One principle: **DEAD != BLOCKED**. Many hosts return 403 to non-browser
User-Agents and reject HEAD with 405 — neither means the page is gone. Only
``404 / 410 / NXDOMAIN`` are DEAD (and only DEAD should fail a build); ``403 / 405
/ 429 / timeout`` are BLOCKED / INCONCLUSIVE and never fatal. Corpus-agnostic; an
adapter decides which URLs to audit.
"""
from __future__ import annotations

import concurrent.futures
import socket
import time
import urllib.error
import urllib.request

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

LIVE, DEAD, BLOCKED, ERROR, INCONCLUSIVE = (
    "live", "dead", "blocked", "error", "inconclusive")


def classify_status(code: int) -> str:
    if 200 <= code < 400:
        return LIVE
    if code in (404, 410):
        return DEAD
    if code in (401, 403, 405, 429):
        return BLOCKED
    if 500 <= code < 600:
        return ERROR
    return INCONCLUSIVE


class _HeadRequest(urllib.request.Request):
    def get_method(self) -> str:
        return "HEAD"


def _probe(url: str, method: str, timeout: int):
    cls = _HeadRequest if method == "HEAD" else urllib.request.Request
    with urllib.request.urlopen(cls(url, headers=_HEADERS), timeout=timeout) as r:
        return r.getcode(), r.geturl()


def check_url(url: str, *, timeout: int = 20, retries: int = 2) -> dict:
    """Probe one URL (HEAD first; retry as GET if HEAD is blocked). DNS failure is
    DEAD immediately; only inconclusive errors are retried. Never raises."""
    last = "unreachable"
    for attempt in range(retries + 1):
        try:
            try:
                code, final = _probe(url, "HEAD", timeout)
            except urllib.error.HTTPError as e:
                if e.code in (400, 403, 405, 501):
                    code, final = _probe(url, "GET", timeout)
                else:
                    raise
            return {"url": url, "status": classify_status(code), "http_code": code,
                    "final_url": final, "detail": "ok"}
        except urllib.error.HTTPError as e:
            return {"url": url, "status": classify_status(e.code), "http_code": e.code,
                    "final_url": url, "detail": f"HTTP {e.code}"}
        except urllib.error.URLError as e:
            reason = getattr(e, "reason", e)
            if isinstance(reason, socket.gaierror):
                return {"url": url, "status": DEAD, "http_code": None,
                        "final_url": url, "detail": f"DNS failure: {reason}"}
            last = f"{type(reason).__name__}: {reason}"
        except Exception as e:                  # noqa: BLE001
            last = f"{type(e).__name__}: {e}"
        if attempt < retries:
            time.sleep(1.5 * (attempt + 1))
    return {"url": url, "status": INCONCLUSIVE, "http_code": None,
            "final_url": url, "detail": last}


def check_urls(urls, *, timeout: int = 20, retries: int = 2, workers: int = 8,
               checker=check_url) -> dict:
    uniq = list(dict.fromkeys(u for u in urls if u))
    out: dict[str, dict] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(checker, u, timeout=timeout, retries=retries): u for u in uniq}
        for fut in concurrent.futures.as_completed(futs):
            u = futs[fut]
            try:
                out[u] = fut.result()
            except Exception as e:              # noqa: BLE001
                out[u] = {"url": u, "status": INCONCLUSIVE, "http_code": None,
                          "final_url": u, "detail": f"{type(e).__name__}: {e}"}
    return out


def audit(adapter, scope: str = "used", *, checker=check_url, workers: int = 8) -> dict:
    """Audit an adapter's authority URLs. Only DEAD links are fatal."""
    url_cites = adapter.index_urls(scope)
    results = check_urls(list(url_cites), checker=checker, workers=workers)
    by_status: dict[str, list] = {}
    for u, r in results.items():
        r["cites"] = url_cites.get(u, [])
        by_status.setdefault(r["status"], []).append(u)
    return {"scope": scope, "checked": len(results),
            "by_status": {k: len(v) for k, v in sorted(by_status.items())},
            "dead": sorted(by_status.get(DEAD, [])), "results": results}
