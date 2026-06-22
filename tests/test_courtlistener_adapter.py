"""Open-vocabulary CourtListener case-law adapter (offline: injected HTTP)."""
import json

from adapters.courtlistener.adapter import CourtListenerCaselawAdapter
from hallucheck import adapter as registry
from hallucheck import research, scan

_SEARCH = {"count": 1, "results": [{
    "caseName": "Estate of Bonin", "citation": ["457 A.2d 1123"],
    "court": "Supreme Judicial Court of Maine", "dateFiled": "1983-04-05",
    "absolute_url": "/opinion/1955225/estate-of-bonin/", "cluster_id": 1955225,
    "citeCount": 10,
    "opinions": [{"id": 1955225, "download_url": None, "snippet": "457 A.2d 1123 (1983) PER CURIAM."}],
}]}


def fake_http(url, *, timeout=20, token=None):
    if "/search/" in url:
        return json.dumps(_SEARCH)
    raise AssertionError(url)


def _adapter():
    return CourtListenerCaselawAdapter(http=fake_http)


def test_registered():
    assert "courtlistener" in registry._REGISTRY


def test_detects_reporter_and_neutral_cites_offline():
    a = _adapter()
    hits = a.citation_spans("See 457 A.2d 1123 and 2000 ME 17 today.")
    cites = {h["cite"] for h in hits}
    assert "457 A.2d 1123" in cites
    assert "2000 ME 17" in cites
    assert all(h["kind"] == "case" and h["resolves"] for h in hits)


def test_resolve_returns_opinion_metadata():
    r = _adapter().resolve("457 A.2d 1123", fetch_text=True)
    assert r["title"] == "Estate of Bonin"
    assert r["url"].endswith("/opinion/1955225/estate-of-bonin/")
    assert "PER CURIAM" in r["text"]


def test_resolve_offline_summary_when_no_fetch():
    r = _adapter().resolve("457 A.2d 1123", fetch_text=False)
    assert "Estate of Bonin" in r["text"] and "1983-04-05" in r["text"]


def test_build_vocabulary_from_scope_confirms_resolution():
    vocab = _adapter().build_vocabulary("457 A.2d 1123")
    assert "457 A.2d 1123" in vocab and vocab["457 A.2d 1123"]["kind"] == "case"


def test_url_in_index_only_judges_courtlistener():
    a = _adapter()
    assert a.url_in_index("https://www.courtlistener.com/opinion/1/x/") is True
    assert a.url_in_index("https://example.com/x") is None


def test_leaked_detection_via_scanner():
    rep = scan.report("As 457 A.2d 1123 holds, we win.", _adapter())
    assert "457 A.2d 1123" in rep["leaked"]
    assert rep["unresolvable"] == []          # open corpus: not flagged offline


def test_packet_over_open_adapter_offline():
    pkt = research.build_packet(_adapter(), cites=["457 A.2d 1123"], fetch_text=True)
    e = pkt["entries"][0]
    assert e["resolved"] and e["kind"] == "case"
    assert e["title"] == "Estate of Bonin"
