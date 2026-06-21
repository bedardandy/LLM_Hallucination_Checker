"""Adversarial battery — mixes of real and fabricated citations, and the evasions
that used to slip past. Each test pins a closed bypass. All offline."""
import json
import types

import pytest

from adapters.maine.adapter import MaineProbateAdapter
from hallucheck import guard, inspector, scan, textnorm

A = MaineProbateAdapter()


def blocks(text, **kw):
    return guard.evaluate(text, A, attest=False, **kw)["block"]


# --- evasions that used to bypass the scanner ------------------------------ #
def test_spelled_out_reverse_order():
    rep = scan.report("The nominee prevails under Section 9-999 of Title 18-C.", A)
    assert "18-C §9-999" in rep["unresolvable"]
    assert blocks("relief under Section 9-999 of Title 18-C", scope="DE-101")


def test_no_protocol_prose_is_blocked():
    # The big hole: skip the protocol, state a *real* statute in prose, mischaracterize
    # it. An unwrapped cite is never substituted/inspected, so it must be blocked.
    text = "The court MUST appoint our client; 18-C §3-401 confers an absolute right."
    assert blocks(text, scope="DE-101")                       # require_protocol default
    assert not blocks(text, scope="DE-101", require_protocol=False)  # opt-out honored


@pytest.mark.parametrize("text,cite", [
    ("See 18‑C §9‑999 for the rule.", "18-C §9-999"),   # non-breaking hyphens
    ("Under 18–C § 9–999 the court acts.", "18-C §9-999"),  # en dashes
    ("See §9-9​99 (fabricated).", "18-C §9-999"),            # zero-width space
    ("See §9-9﻿99.", "18-C §9-999"),                         # BOM inside number
])
def test_homoglyph_and_zero_width_evasion(text, cite):
    rep = scan.report(text, A, scope="DE-101")
    assert cite in rep["unresolvable"], rep
    assert blocks(text, scope="DE-101")


def test_out_of_scope_cite_wrapped_in_placeholder_blocks():
    # 18-C §9-306 is real but not in DE-101's vocabulary; wrapping it in a valid
    # placeholder must not launder it past the offline guard (parity with Gate A).
    text = "Per [[REF: 18-C §9-306]] the personal representative may sell."
    rep = scan.report(text, A, scope="DE-101")
    assert rep["out_of_vocab"] == ["18-C §9-306"]
    assert rep["unresolvable"] == [] and rep["leaked"] == []
    assert blocks(text, scope="DE-101")


# --- mixed real + fabricated, all in one draft ----------------------------- #
def test_mixed_buckets_in_one_draft():
    text = ("Good: [[REF: 18-C §3-401]]. Smuggled real cite 18-C §3-203. "
            "Fabricated 18-C §9-999. Out-of-scope wrapped [[REF: 18-C §9-306]]. "
            "Fake link https://example.com/x.")
    rep = scan.report(text, A, scope="DE-101")
    assert "18-C §3-203" in rep["leaked"] and "18-C §9-999" in rep["leaked"]
    assert "18-C §9-999" in rep["unresolvable"]
    assert "18-C §9-306" in rep["out_of_vocab"]
    assert "https://example.com/x" in rep["fabricated_urls"]
    # the one correctly-wrapped, in-scope cite is in none of the problem buckets
    for bucket in ("leaked", "unresolvable", "out_of_vocab"):
        assert "18-C §3-401" not in rep[bucket]


def test_plural_section_list_catches_every_item():
    # "§§ 3-401, 3-203 and 9-999" must not let the fabricated 9-999 hide behind the
    # first item.
    rep = scan.report("The court applies §§ 3-401, 3-203 and 9-999.", A, scope="DE-101")
    assert "18-C §9-999" in rep["unresolvable"]
    assert {"18-C §3-401", "18-C §3-203", "18-C §9-999"} <= set(rep["leaked"])


def test_subsection_key_is_not_a_false_positive():
    # A valid section cited with a subsection must still resolve (no false "invented").
    assert A._resolves("18-C §3-401(a)")
    assert A.resolve("18-C §3-401(a)", fetch_text=False)["title"]
    out, cites = inspector.substitute(
        "[[REF: 18-C §3-401(a)]]", {"18-C §3-401(a)"},
        lambda k: A.resolve(k, fetch_text=False))
    assert cites[0]["status"] == "resolved"


def test_case_names_and_reporter_cites():
    rep = scan.report("As in In re Estate of Kruzynski, and the made-up 999 A.2d 1.", A)
    cites = {h["cite"] for h in rep["hits"]}
    assert "2000 ME 17" in cites                              # resolved from the name
    assert "999 A.2d 1" in rep["unresolvable"]               # fabricated reporter cite


# --- URL classification edge cases ----------------------------------------- #
def test_url_classes():
    text = ("real https://legislature.maine.gov/statutes/18-C/title18-Csec3-401.html "
            "fake https://legislature.maine.gov/statutes/18-C/title18-Csec99-999.html "
            "markdown [x](https://example.com/x) "
            "unknown host https://courts.maine.gov/opinions/2099/fake.pdf")
    rep = scan.report(text, A)
    cls = {h["url"].rsplit("/", 1)[-1]: h["class"] for h in rep["urls"]}
    assert cls["title18-Csec3-401.html"] == "known"
    assert cls["title18-Csec99-999.html"] == "fabricated"
    assert cls["x"] == "placeholder"
    assert cls["fake.pdf"] == "unknown"                      # documented limitation
    assert "https://courts.maine.gov/opinions/2099/fake.pdf" in rep["unknown_urls"]


def test_check_live_probes_unknown_urls(monkeypatch):
    from hallucheck import links
    monkeypatch.setattr(links, "check_url",
                        lambda u, **k: {"url": u, "status": "dead"})
    rep = scan.report("https://courts.maine.gov/opinions/2099/fake.pdf", A, check_live=True)
    assert rep["dead_urls"] == ["https://courts.maine.gov/opinions/2099/fake.pdf"]


# --- normalization invariants ---------------------------------------------- #
def test_clean_idempotent_and_strips_invisibles():
    raw = "18‑C §3​-401‮"
    once = textnorm.clean(raw)
    assert textnorm.clean(once) == once                      # idempotent
    assert "​" not in once and "‮" not in once     # zero-width/bidi gone
    assert "18-C" in once                                     # hyphen folded


# --- inspector-level evasions ---------------------------------------------- #
def _stub(payload):
    def create(**_):
        m = types.SimpleNamespace(content=payload, reasoning_content="")
        return types.SimpleNamespace(choices=[types.SimpleNamespace(message=m)])
    return types.SimpleNamespace(
        chat=types.SimpleNamespace(completions=types.SimpleNamespace(create=create)))


_TEXT = {"A1": "On notice the body shall enter an order so determining.",
         "A2": "The fiduciary may act only after court authorization."}


def _resolver(key):
    return {"cite": key, "title": key, "url": "u", "text": _TEXT.get(key, "")}


def test_inspector_flags_dropped_verdict():
    # Two resolved cites, inspector returns a verdict for only one -> the other
    # must not pass silently.
    payload = json.dumps({"verdicts": [{"cite": "A1", "supports_conclusion": "pass",
                                        "quote": "shall enter an order", "rationale": "ok"}]})
    res = inspector.inspect("[[REF: A1]] and [[REF: A2]]", {"A1", "A2"}, _resolver,
                            client=_stub(payload), model="m")
    by = {v["cite"]: v for v in res["verdicts"]}
    assert by["A2"]["unreviewed"] is True
    assert by["A2"]["supports_conclusion"] == "unclear"
    assert res["summary"]["unclear"] >= 1


def test_inspector_mixed_invented_unresolved_resolved():
    # one valid (resolves), one out-of-vocab (Gate A invented), one in-vocab but
    # unresolvable (Gate B). No LLM needed for the deterministic gates.
    out, cites = inspector.substitute(
        "[[REF: A1]] [[REF: NOPE]] [[REF: A2]]", {"A1", "A2"},
        lambda k: _resolver(k) if k == "A1" else None)
    status = {c["key"]: c["status"] for c in cites}
    assert status == {"A1": "resolved", "NOPE": "invented", "A2": "unresolved"}
    assert "[[INVENTED: NOPE]]" in out and "[[UNRESOLVED: A2]]" in out
