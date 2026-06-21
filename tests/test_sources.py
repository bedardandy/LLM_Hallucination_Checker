"""Source-link assembly: real, constructible links only; subscription/bar portals
are labeled, never fabricated deep links."""
from hallucheck import sources


def test_reporter_redirect_builds_courtlistener_citation():
    assert sources.reporter_redirect("457 A.2d 1123") == \
        "https://www.courtlistener.com/c/A.2d/457/1123/"
    assert sources.reporter_redirect("2014 ME 2") is None      # neutral cite, not a reporter


def test_case_links_include_scholar_and_courtlistener():
    out = sources.for_citation({"cite": "457 A.2d 1123", "kind": "case",
                                "name": "Estate of Bonin"})
    assert out["kind"] == "case"
    providers = {ln["provider"] for ln in out["links"]}
    assert "google_scholar" in providers
    assert "courtlistener" in providers          # reporter cite -> deep link
    assert "google_web" in providers


def test_neutral_cite_inferred_as_case_without_explicit_kind():
    out = sources.for_citation({"cite": "2000 ME 17"})
    assert out["kind"] == "case"
    assert any(ln["provider"] == "google_scholar" for ln in out["links"])


def test_statute_has_official_link_and_no_scholar():
    out = sources.for_citation({"cite": "18-C §3-108", "kind": "statute",
                                "url": "https://legislature.maine.gov/x.html"})
    assert out["kind"] == "statute"
    providers = {ln["provider"] for ln in out["links"]}
    assert "official" in providers
    assert "google_scholar" not in providers     # case-only service
    assert "wayback" in providers                # snapshot of the official URL


def test_no_official_link_when_no_url():
    out = sources.for_citation({"cite": "18-C §9-999", "kind": "statute"})
    assert all(ln["provider"] != "official" for ln in out["links"])
    assert out["snapshot"] is None               # nothing to archive -> no fabricated URL


def test_portals_require_login_and_carry_query():
    out = sources.for_citation({"cite": "2000 ME 17", "kind": "case"})
    assert out["portals"], "expected subscription + bar portals"
    for p in out["portals"]:
        assert p["requires_login"] is True
        assert p["query"] == "2000 ME 17"
        assert p["portal_url"].startswith("https://")
        assert "url" not in p                     # never a guessed document deep link
    labels = {p["provider"] for p in out["portals"]}
    assert {"westlaw", "lexis"} <= labels         # subscription
    assert any("bar" in p["access"] for p in out["portals"])   # bar membership tier


def test_wayback_save_and_view():
    wb = sources.wayback("https://example.gov/x")
    assert wb["save_url"].endswith("/save/https://example.gov/x")
    assert "web/*/" in wb["view_url"]
