"""Adversarial authority-use review workflow tests."""
from adapters.maine.adapter import MaineProbateAdapter
from hallucheck import challenge, research


def test_challenge_flags_overstatement_and_builds_counter_queries():
    entry = {
        "cite": "2000 ME 17",
        "title": "In re Estate of Kruzynski",
        "kind": "case",
        "text": "The court held the petition was time-barred. However, it did not decide tolling.",
        "text_sha256": "abc",
    }
    res = challenge.analyze_authority_use(
        entry, claim="Kruzynski always forecloses tolling and controls every late petition.")
    kinds = {w["kind"] for w in res["warnings"]}
    assert "overstatement_risk" in kinds
    assert "limiting_language_not_reflected" in kinds
    assert any("overruled" in q for q in res["counter_treatment_queries"])
    assert any(c["kind"] == "holding_vs_dicta" for c in res["logical_leap_checks"])


def test_statutory_challenge_includes_legislative_history_queries():
    entry = {"cite": "18-C §3-108", "title": "Probate limitation", "kind": "statute", "text": ""}
    res = challenge.analyze_authority_use(entry, claim="The statute controls.")
    assert any("legislative history" in q for q in res["legislative_history_queries"])
    assert any("effective date" in q for q in res["legislative_history_queries"])


def test_research_packet_embeds_challenge_review_from_draft():
    draft = "In re Estate of Kruzynski always controls any late probate petition."
    pkt = research.build_packet(MaineProbateAdapter(), cites=["2000 ME 17"], draft=draft,
                                fetch_text=False)
    entry = next(e for e in pkt["entries"] if e["cite"] == "2000 ME 17")
    assert entry["challenge"]["claim_contexts"]
    assert entry["challenge"]["adversarial_questions"]
