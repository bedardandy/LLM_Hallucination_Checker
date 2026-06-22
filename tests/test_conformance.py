"""The adapter conformance kit, run against both bundled adapters + a broken one."""
import json

from adapters.courtlistener.adapter import CourtListenerCaselawAdapter
from adapters.maine.adapter import MaineProbateAdapter
from hallucheck import conformance


def test_maine_conforms():
    conformance.assert_conforms(
        MaineProbateAdapter(),
        sample_text="Under 18-C §3-108 and In re Estate of Kruzynski the claim fails.",
        resolves_cites=["18-C §3-108", "2000 ME 17"], in_scope="DE-101")


def _cl_http(url, *, timeout=20, token=None):
    if "/search/" in url:
        return json.dumps({"count": 1, "results": [{
            "caseName": "Estate of Bonin", "citation": ["457 A.2d 1123"],
            "court": "Me.", "dateFiled": "1983-04-05",
            "absolute_url": "/opinion/1955225/estate-of-bonin/", "cluster_id": 1955225,
            "citeCount": 10, "opinions": [{"id": 1955225, "snippet": "PER CURIAM."}]}]})
    raise AssertionError(url)


def test_courtlistener_conforms():
    conformance.assert_conforms(
        CourtListenerCaselawAdapter(http=_cl_http),
        sample_text="See 457 A.2d 1123 for the rule.",
        resolves_cites=["457 A.2d 1123"], in_scope="457 A.2d 1123")


class _BrokenAdapter:
    name = "broken"
    disclaimer = ""                                       # empty -> problem
    def build_vocabulary(self, scope=None):
        return ["not", "a", "dict"]                       # wrong type -> problem
    def resolve(self, key, *, fetch_text=True):
        return None
    def citation_spans(self, text, *, scope=None):
        return "not a list"                               # wrong type -> problem
    def url_in_index(self, url):
        return "maybe"                                    # not True/False/None -> problem
    def index_urls(self, scope="used"):
        return {}
    def config_digest(self):
        return 123                                        # not a str -> problem


def test_kit_catches_violations():
    problems = conformance.check(_BrokenAdapter(), sample_text="x")
    joined = "\n".join(problems)
    assert "disclaimer" in joined
    assert "build_vocabulary must return a dict" in joined
    assert "citation_spans" in joined
    assert "url_in_index" in joined
    assert "config_digest must return a str" in joined


def test_missing_method_is_reported():
    class NoMethods:
        name = "x"
        disclaimer = "y"
    problems = conformance.check(NoMethods())
    assert any("does not satisfy the Adapter protocol" in p for p in problems)
