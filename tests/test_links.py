"""Dead-link checker tests (monkeypatched urlopen; no network)."""
import socket
import urllib.error

from hallucheck import links


class _Resp:
    def __init__(self, code, url):
        self._code, self._url = code, url

    def getcode(self):
        return self._code

    def geturl(self):
        return self._url

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _fake(spec):
    def fake(req, timeout=None):
        url, method = req.full_url, req.get_method()
        if spec == "live200":
            return _Resp(200, url)
        if spec.startswith("http"):
            raise urllib.error.HTTPError(url, int(spec[4:]), "x", {}, None)
        if spec == "head405":
            if method == "HEAD":
                raise urllib.error.HTTPError(url, 405, "m", {}, None)
            return _Resp(200, url)
        if spec == "dns":
            raise urllib.error.URLError(socket.gaierror("no such host"))
        if spec == "timeout":
            raise urllib.error.URLError(TimeoutError("timed out"))
        raise AssertionError(spec)
    return fake


def test_classify_status():
    assert links.classify_status(200) == links.LIVE
    assert links.classify_status(404) == links.DEAD
    assert links.classify_status(403) == links.BLOCKED      # not dead
    assert links.classify_status(500) == links.ERROR


def test_check_url_variants(monkeypatch):
    monkeypatch.setattr("urllib.request.urlopen", _fake("live200"))
    assert links.check_url("https://x/a")["status"] == links.LIVE
    monkeypatch.setattr("urllib.request.urlopen", _fake("http404"))
    assert links.check_url("https://x/gone")["status"] == links.DEAD
    monkeypatch.setattr("urllib.request.urlopen", _fake("http403"))
    assert links.check_url("https://x/blocked")["status"] == links.BLOCKED
    monkeypatch.setattr("urllib.request.urlopen", _fake("head405"))
    assert links.check_url("https://x/headblock")["status"] == links.LIVE
    monkeypatch.setattr("urllib.request.urlopen", _fake("dns"))
    assert links.check_url("https://nope.invalid", retries=0)["status"] == links.DEAD
    monkeypatch.setattr("urllib.request.urlopen", _fake("timeout"))
    assert links.check_url("https://slow", retries=0)["status"] == links.INCONCLUSIVE


def test_audit_over_maine_adapter():
    from adapters.maine.adapter import MaineProbateAdapter
    rep = links.audit(MaineProbateAdapter(), "used",
                      checker=lambda u, **k: {"url": u, "status": links.LIVE,
                                              "http_code": 200, "final_url": u, "detail": "ok"})
    assert rep["dead"] == [] and rep["checked"] > 0
