"""Maine adapter tests — vocabulary, resolution, URL index, statute extraction."""
import pathlib
import urllib.error

from adapters.maine import fetch
from adapters.maine.adapter import MaineProbateAdapter

A = MaineProbateAdapter()
FIX = pathlib.Path(__file__).resolve().parent / "fixtures" / "sec3-108.html"


def test_build_vocabulary_scoped():
    vocab = A.build_vocabulary("DE-101")
    assert "18-C §3-401" in vocab and vocab["18-C §3-401"]["kind"] == "statute"
    assert "18-C §9-306" not in vocab          # belongs to AD-008, not DE-101


def test_resolve_offline_uses_title_and_note():
    auth = A.resolve("18-C §3-401", fetch_text=False)
    assert auth and "Formal testacy" in auth["text"]


def test_resolve_dead_link(monkeypatch):
    def boom(url, timeout=60):
        raise urllib.error.HTTPError(url, 404, "gone", {}, None)
    monkeypatch.setattr(fetch, "_download", boom)
    auth = A.resolve("18-C §3-401", fetch_text=True)
    assert auth and auth.get("dead_link") is True


def test_resolve_case_holding():
    auth = A.resolve("2000 ME 17", fetch_text=False)
    assert auth and "Holding" in auth["text"]


def test_url_in_index():
    base = "https://legislature.maine.gov/statutes/18-C/"
    assert A.url_in_index(base + "title18-Csec3-401.html") is True
    assert A.url_in_index(base + "title18-Csec99-999.html") is False
    assert A.url_in_index("https://law.justia.com/cases/maine/x") is None


def test_extract_statute_text_strips_chrome():
    text = fetch.extract_statute_text(FIX.read_text(encoding="utf-8"), "18-C §3-108")
    assert "ultimate time limit" in text
    assert "Bills & Laws" not in text and "Revisor" not in text


def test_config_digest_stable():
    assert len(A.config_digest()) == 16 and A.config_digest() == A.config_digest()
