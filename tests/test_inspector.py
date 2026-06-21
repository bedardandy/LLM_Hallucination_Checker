"""Generic engine tests — placeholders, gates, inspect (stub client), grounding."""
import json
import types

from hallucheck import inspector as li


def make_stub(payload):
    def create(**_kw):
        msg = types.SimpleNamespace(content=payload, reasoning_content="")
        return types.SimpleNamespace(choices=[types.SimpleNamespace(message=msg)])
    return types.SimpleNamespace(
        chat=types.SimpleNamespace(completions=types.SimpleNamespace(create=create)))


def _resolver(_key):
    return {"cite": "X1", "title": "T", "url": "u",
            "text": "After notice the body enters an order determining the result."}


def test_extract_refs_ordered_unique():
    assert li.extract_refs("a [[REF:K1]] [[REF:  K2 ]] [[REF: K1]]") == ["K1", "K2"]


def test_substitute_gate_a_invented():
    out, cites = li.substitute("see [[REF: Nope]]", {"K"}, _resolver)
    assert "[[INVENTED: Nope]]" in out and cites[0]["status"] == "invented"


def test_substitute_gate_b_unresolved():
    out, cites = li.substitute("see [[REF: K]]", {"K"}, lambda k: None)
    assert "[[UNRESOLVED: K]]" in out and cites[0]["status"] == "unresolved"


def test_substitute_dead_link():
    out, cites = li.substitute("see [[REF: K]]", {"K"},
                               lambda k: {"cite": "K", "text": None, "dead_link": True})
    assert "[[DEAD LINK: K]]" in out and cites[0]["status"] == "dead_link"


def test_substitute_resub_handles_duplicates():
    out, cites = li.substitute("[[REF: K]] and [[REF: K]]", {"K"},
                               lambda k: {"cite": "K", "text": "BODY", "title": "T"})
    assert out.count("BODY") == 2
    assert len([c for c in cites if c["status"] == "resolved"]) == 1


def test_inspect_fail_with_grounded_quote():
    payload = json.dumps({"verdicts": [{"cite": "X1", "supports_conclusion": "fail",
                                        "quote": "enters an order determining the result",
                                        "rationale": "overstated"}]})
    res = li.inspect("Under [[REF: X1]] we win.", {"X1"}, _resolver,
                     client=make_stub(payload), model="m")
    assert res["ok"] and res["verdicts"][0]["supports_conclusion"] == "fail"
    assert res["verdicts"][0]["quote_grounded"] is True
    assert res["summary"]["fail"] == 1


def test_inspect_downgrades_fabricated_quote():
    payload = json.dumps({"verdicts": [{"cite": "X1", "supports_conclusion": "pass",
                                        "quote": "absolute unlimited power", "rationale": "x"}]})
    res = li.inspect("[[REF: X1]]", {"X1"}, _resolver, client=make_stub(payload), model="m")
    assert res["verdicts"][0]["quote_grounded"] is False
    assert res["verdicts"][0]["supports_conclusion"] == "unclear"


def test_inspect_fails_soft_without_client(monkeypatch):
    def boom():
        raise RuntimeError("no endpoint")
    monkeypatch.setattr(li, "_client", boom)
    res = li.inspect("[[REF: X1]]", {"X1"}, _resolver)
    assert res["ok"] is False and "unavailable" in res["error"]
