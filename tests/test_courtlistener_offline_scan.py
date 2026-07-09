"""The CourtListener open adapter's deterministic scanner MUST be offline.

THREATS.md / the ``Adapter`` protocol promise the deterministic scanner is
"offline … fail-closed and LLM-free — safe in a blocking hook". The open adapter
regressed this: ``citation_spans(scope=...)`` used to call ``build_vocabulary`` →
``resolve`` → the CourtListener network during a scan, so ``scan.report`` /
``guard.evaluate`` made blocking network calls.

These tests pin the contract: scanning never resolves over the network. Network
resolution is confined to the explicit ``build_vocabulary`` / ``resolve`` prime
step, whose cached result a later offline scan may consult.
"""

from __future__ import annotations

import json

import pytest

from adapters.courtlistener.adapter import CourtListenerCaselawAdapter
from hallucheck import scan

_SEARCH = {"count": 1, "results": [{
    "caseName": "Estate of Bonin", "citation": ["457 A.2d 1123"],
    "court": "Supreme Judicial Court of Maine", "dateFiled": "1983-04-05",
    "absolute_url": "/opinion/1955225/estate-of-bonin/", "cluster_id": 1955225,
    "citeCount": 10,
    "opinions": [{"id": 1955225, "download_url": None,
                  "snippet": "457 A.2d 1123 (1983) PER CURIAM."}],
}]}


def _fake_http(url, *, timeout=20, token=None):
    if "/search/" in url:
        return json.dumps(_SEARCH)
    raise AssertionError(url)


def _no_network_resolve(*_a, **_kw):
    raise AssertionError("resolve() called during an offline scan (network!)")


def test_citation_spans_never_resolves_over_network():
    a = CourtListenerCaselawAdapter()
    a.resolve = _no_network_resolve  # any resolution attempt is a hard failure
    hits = a.citation_spans("See 457 A.2d 1123 and 2000 ME 17 today.", scope="457 A.2d 1123")
    cites = {h["cite"] for h in hits}
    assert "457 A.2d 1123" in cites
    assert "2000 ME 17" in cites
    # Unprimed + offline: membership is simply unknown, never network-confirmed.
    assert all(h.get("in_vocab") is False for h in hits)


def test_scan_report_with_scope_is_offline():
    a = CourtListenerCaselawAdapter()
    a.resolve = _no_network_resolve
    rep = scan.report("As 457 A.2d 1123 holds, we win.", a, scope="457 A.2d 1123")
    assert "457 A.2d 1123" in rep["leaked"]
    # out_of_vocab is computed offline from the (empty, unprimed) vocabulary.
    assert "out_of_vocab" in rep


def test_scan_without_scope_is_offline():
    a = CourtListenerCaselawAdapter()
    a.resolve = _no_network_resolve
    rep = scan.report("As 457 A.2d 1123 holds, we win.", a)
    assert "457 A.2d 1123" in rep["leaked"]


def test_explicit_prime_then_offline_scan_marks_in_vocab():
    # Consumers that DO explicitly resolve keep their behavior: build_vocabulary
    # (network, here via injected http) primes the cache; the later scan reads it
    # offline and reflects the seeded membership without touching the network.
    a = CourtListenerCaselawAdapter(http=_fake_http)
    a.build_vocabulary("457 A.2d 1123")  # explicit prime step
    a.resolve = _no_network_resolve      # now forbid any further network use
    hits = a.citation_spans("See 457 A.2d 1123 and 999 A.3d 1 today.", scope="457 A.2d 1123")
    by_cite = {h["cite"]: h for h in hits}
    assert by_cite["457 A.2d 1123"]["in_vocab"] is True
    assert by_cite["999 A.3d 1"]["in_vocab"] is False


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v"]))
