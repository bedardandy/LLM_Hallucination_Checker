"""CourtListener enrichment — deterministic, offline (HTTP layer is injected)."""
import json

import pytest

from adapters.maine.adapter import MaineProbateAdapter
from hallucheck import courtlistener, embed, research

_SEARCH = {
    "count": 1,
    "results": [{
        "caseName": "Estate of Bonin",
        "citation": ["457 A.2d 1123", "1983 Me. LEXIS 667"],
        "court": "Supreme Judicial Court of Maine",
        "dateFiled": "1983-04-05",
        "citeCount": 10,
        "absolute_url": "/opinion/1955225/estate-of-bonin/",
        "cluster_id": 1955225,
        "opinions": [{"id": 1955225, "download_url": None,
                      "snippet": "457 A.2d 1123 (1983)\nESTATE OF Ernest F. BONIN, Sr."}],
    }],
}
_CITING = {"count": 2, "results": [
    {"caseName": "Later Case A", "court": "Me.", "dateFiled": "2010-01-01",
     "citation": ["2010 ME 1"], "absolute_url": "/opinion/111/later-a/"},
    {"caseName": "Later Case B", "court": "Me.", "dateFiled": "2005-01-01",
     "citation": ["2005 ME 9"], "absolute_url": "/opinion/222/later-b/"},
]}
_OPINION = {"plain_text": "PER CURIAM. ...", "download_url": None,
            "local_path": "pdf/1983/estate-of-bonin.pdf"}


def fake_http(url, *, timeout=20, token=None):
    if "/opinions/" in url:
        return json.dumps(_OPINION)
    if "cites" in url:                      # q=cites:(<id>) -> citing-opinions search
        return json.dumps(_CITING)
    if "/search/" in url:
        return json.dumps(_SEARCH)
    raise AssertionError(f"unexpected url {url}")


def boom_http(url, *, timeout=20, token=None):
    raise OSError("network down")


def test_lookup_parses_real_shape():
    r = courtlistener.lookup("457 A.2d 1123", http=fake_http)
    assert r["found"] is True
    assert r["case_name"] == "Estate of Bonin"
    assert r["opinion_id"] == 1955225
    assert r["absolute_url"] == "https://www.courtlistener.com/opinion/1955225/estate-of-bonin/"
    assert "457 A.2d 1123" in r["citations"]
    assert r["snippet"]


def test_lookup_includes_cite_count():
    r = courtlistener.lookup("457 A.2d 1123", http=fake_http)
    assert r["cite_count"] == 10


def test_citing_lists_recent_first_and_truncates():
    c = courtlistener.citing(1955225, limit=1, http=fake_http)
    assert c["count"] == 2
    assert len(c["opinions"]) == 1                       # truncated to limit
    o = c["opinions"][0]
    assert o["case_name"] == "Later Case A"
    assert o["absolute_url"] == "https://www.courtlistener.com/opinion/111/later-a/"
    assert "cites:(1955225)" in c["search_url"]


def test_citing_never_raises():
    c = courtlistener.citing(1, http=boom_http)
    assert c == {"count": 0, "opinions": [], "error": c["error"]}
    assert "OSError" in c["error"]


def test_enrich_attaches_citing_when_requested():
    case = {"cite": "457 A.2d 1123", "kind": "case",
            "sources": {"links": [], "portals": []}}
    courtlistener.enrich(case, http=fake_http, citing_limit=2)
    assert len(case["courtlistener"]["citing"]["opinions"]) == 2


def test_lookup_no_results():
    r = courtlistener.lookup("999 A.2d 999", http=lambda *a, **k: json.dumps({"results": []}))
    assert r["found"] is False


def test_lookup_never_raises_on_network_error():
    r = courtlistener.lookup("457 A.2d 1123", http=boom_http)
    assert r["found"] is False
    assert "OSError" in r["error"]


def test_enrich_adds_links_for_case_only():
    case = {"cite": "457 A.2d 1123", "kind": "case",
            "sources": {"links": [], "portals": []}}
    courtlistener.enrich(case, http=fake_http)
    assert case["courtlistener"]["found"] is True
    assert any(l["provider"] == "courtlistener_opinion" for l in case["sources"]["links"])

    statute = {"cite": "18-C §3-108", "kind": "statute",
               "sources": {"links": [], "portals": []}}
    courtlistener.enrich(statute, http=fake_http)
    assert "courtlistener" not in statute        # no-op for non-cases


def test_build_packet_with_courtlistener_and_rendering():
    pkt = research.build_packet(MaineProbateAdapter(), cites=["457 A.2d 1123"],
                                fetch_text=False, courtlistener_lookup=True,
                                cl_http=fake_http)
    e = pkt["entries"][0]
    assert e["courtlistener"]["found"] is True
    assert pkt["counts"]["courtlistener"] == 1
    md = embed.to_markdown(pkt)
    assert "CourtListener:" in md
    assert "Estate of Bonin" in md
    htmls = embed.to_html(pkt)
    assert "courtlistener.com/opinion/1955225" in htmls


def test_packet_citing_renders_treatment_review_block():
    pkt = research.build_packet(MaineProbateAdapter(), cites=["457 A.2d 1123"],
                                fetch_text=False, courtlistener_lookup=True,
                                cl_http=fake_http, cl_citing_limit=2)
    e = pkt["entries"][0]
    assert e["courtlistener"]["citing"]["count"] == 2
    md = embed.to_markdown(pkt)
    assert "Cited by ~2 later opinion(s)" in md
    assert "review for negative treatment" in md
    assert "Later Case A" in md
    htmls = embed.to_html(pkt)
    assert "courtlistener.com/opinion/111/later-a/" in htmls


def test_citing_packet_renders_docx_and_pdf(tmp_path):
    pkt = research.build_packet(MaineProbateAdapter(), cites=["457 A.2d 1123"],
                                fetch_text=False, courtlistener_lookup=True,
                                cl_http=fake_http, cl_citing_limit=2)
    pytest.importorskip("docx")
    embed.to_docx(pkt, str(tmp_path / "a.docx"))
    pytest.importorskip("reportlab")
    p = tmp_path / "a.pdf"
    embed.to_pdf(pkt, str(p))
    assert p.read_bytes().startswith(b"%PDF")


@pytest.mark.parametrize("bad", [
    "file:///etc/passwd",                      # local file read
    "ftp://ftp.example.com/x",                 # non-http scheme
    "http://169.254.169.254/latest/meta-data/",  # cloud metadata (link-local)
    "http://127.0.0.1/x",                      # loopback
    "http://10.1.2.3/x",                       # private
    "https://[::1]/x",                         # IPv6 loopback
])
def test_assert_fetchable_blocks_ssrf(bad):
    with pytest.raises(ValueError):
        courtlistener._assert_fetchable(bad)


@pytest.mark.parametrize("ok", ["https://1.1.1.1/op.pdf", "http://8.8.8.8/op"])
def test_assert_fetchable_allows_public(ok):
    courtlistener._assert_fetchable(ok)         # no raise


def test_fetch_file_refuses_bad_url_without_writing(tmp_path):
    dest = tmp_path / "x.pdf"
    with pytest.raises(ValueError):
        courtlistener.fetch_file("file:///etc/passwd", str(dest))
    assert not dest.exists()


def test_fetch_file_enforces_size_cap(tmp_path, monkeypatch):
    class FakeResp:
        def __init__(self, data): self.data, self.pos = data, 0
        def read(self, n=-1):
            chunk = self.data[self.pos:self.pos + (n if n and n > 0 else len(self.data))]
            self.pos += len(chunk)
            return chunk
        def __enter__(self): return self
        def __exit__(self, *a): return False

    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: FakeResp(b"x" * 100))
    dest = tmp_path / "big.pdf"
    with pytest.raises(ValueError):
        courtlistener.fetch_file("https://1.1.1.1/big.pdf", str(dest), max_bytes=10)
    assert not dest.exists()                     # partial file cleaned up


def test_attach_opinions_downloads_and_links(tmp_path):
    pkt = research.build_packet(MaineProbateAdapter(), cites=["457 A.2d 1123"],
                                fetch_text=False, courtlistener_lookup=True,
                                cl_http=fake_http)
    saved_to = {}

    def fake_fetch(url, dest, *, token=None):
        with open(dest, "wb") as fh:
            fh.write(b"%PDF-1.4 fake")
        saved_to["url"], saved_to["dest"] = url, dest
        return dest

    n = research.attach_opinions(pkt, str(tmp_path), http=fake_http, fetch=fake_fetch)
    assert n == 1
    assert saved_to["url"].endswith("pdf/1983/estate-of-bonin.pdf")
    links = pkt["entries"][0]["sources"]["links"]
    assert any(l["provider"] == "local_opinion_file" for l in links)
