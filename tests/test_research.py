"""Verification-packet builder over the Maine adapter (offline: --no-fetch)."""
from adapters.maine.adapter import MaineProbateAdapter
from hallucheck import research


def _adapter():
    return MaineProbateAdapter()


def test_packet_from_explicit_cites_resolves_offline():
    pkt = research.build_packet(
        _adapter(), cites=["2000 ME 17", "18-C §3-108", "457 A.2d 1123"],
        fetch_text=False)
    assert pkt["schema"] == research.SCHEMA
    assert pkt["counts"]["total"] == 3
    by = {e["cite"]: e for e in pkt["entries"]}
    assert by["2000 ME 17"]["resolved"] is True
    assert by["2000 ME 17"]["text_sha256"]
    assert by["2000 ME 17"]["kind"] == "case"
    assert by["18-C §3-108"]["kind"] == "statute"
    # every authority carries source links + portals
    assert by["18-C §3-108"]["sources"]["links"]
    assert by["2000 ME 17"]["sources"]["portals"]


def test_disclaimer_is_stamped():
    pkt = research.build_packet(_adapter(), cites=["18-C §3-108"], fetch_text=False)
    assert "NOT LEGAL ADVICE" in pkt["disclaimer"]
    assert "licensed attorney" in pkt["disclaimer"].lower()


def test_cross_linking_case_to_statute():
    # Kruzynski's holding text names 18-C §3-108 -> bidirectional related link.
    pkt = research.build_packet(_adapter(), cites=["2000 ME 17", "18-C §3-108"],
                                fetch_text=False)
    by = {e["cite"]: e for e in pkt["entries"]}
    rel_case = {r["cite"] for r in by["2000 ME 17"]["related"]}
    rel_stat = {r["cite"] for r in by["18-C §3-108"]["related"]}
    assert "18-C §3-108" in rel_case
    assert "2000 ME 17" in rel_stat


def test_extract_and_build_from_draft():
    draft = ("Under 18-C §3-108 a proceeding is time-barred, and In re Estate of "
             "Kruzynski confirms the three-year limit.")
    pkt = research.build_packet(_adapter(), draft=draft, fetch_text=False)
    cites = {e["cite"] for e in pkt["entries"]}
    assert "18-C §3-108" in cites
    assert "2000 ME 17" in cites              # matched by case name
    assert pkt["from_draft"] is True


def test_unresolved_cite_is_flagged_not_silently_passed():
    pkt = research.build_packet(_adapter(), cites=["18-C §9-999"], fetch_text=False)
    e = pkt["entries"][0]
    assert e["resolved"] is False
    assert "18-C §9-999" in pkt["unverified"]


def test_treatment_authorities_get_internal_anchor():
    treatments = {"2000 ME 17": {"status": "caution",
                                 "note": "confirm carry-forward to 18-C",
                                 "authorities": [{"cite": "18-C §3-108",
                                                  "label": "successor statute"}]}}
    pkt = research.build_packet(_adapter(), cites=["2000 ME 17", "18-C §3-108"],
                                fetch_text=False, treatments=treatments)
    by = {e["cite"]: e for e in pkt["entries"]}
    auth = by["2000 ME 17"]["treatment"]["authorities"][0]
    assert auth["anchor"] == by["18-C §3-108"]["anchor"]
    assert by["2000 ME 17"]["treatment"]["status"] == "caution"
    assert pkt["counts"]["treated"] == 1
