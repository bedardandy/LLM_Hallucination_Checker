"""Scanner tests over the Maine adapter (deterministic, offline)."""
from adapters.maine.adapter import MaineProbateAdapter
from hallucheck import scan

A = MaineProbateAdapter()


def test_citation_spans_finds_statutes_and_case_names():
    cites = {h["cite"] for h in A.citation_spans(
        "Under 18-C §3-401 and In re Estate of Kruzynski, see also §3-203.")}
    assert "18-C §3-401" in cites
    assert "18-C §3-203" in cites
    assert "2000 ME 17" in cites          # resolved from the case name


def test_report_buckets_leaked_unresolvable_and_urls():
    text = ("Under [[REF: 18-C §3-401]] the court acts; see also 18-C §3-203, the "
            "made-up 18-C §9-999, and https://example.com/x.")
    rep = scan.report(text, A, scope="DE-101")
    assert rep["leaked"] == ["18-C §3-203"] or "18-C §3-203" in rep["leaked"]
    assert "18-C §9-999" in rep["unresolvable"]
    assert "https://example.com/x" in rep["fabricated_urls"]


def test_out_of_vocab_is_scope_specific():
    rep = scan.report("citing 18-C §9-306 here", A, scope="DE-101")
    assert "18-C §9-306" in rep["out_of_vocab"]
    assert "18-C §9-306" not in rep["unresolvable"]   # resolves globally


def test_fabricated_statute_url_offline():
    rep = scan.report(
        "real https://legislature.maine.gov/statutes/18-C/title18-Csec3-401.html "
        "fake https://legislature.maine.gov/statutes/18-C/title18-Csec99-999.html", A)
    classes = {h["url"].rsplit("/", 1)[-1]: h["class"] for h in rep["urls"]}
    assert classes["title18-Csec3-401.html"] == "known"
    assert classes["title18-Csec99-999.html"] == "fabricated"
