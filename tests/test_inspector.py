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


# --- provider abstraction (OpenAI-compatible + Anthropic) ------------------- #
def make_anthropic_stub(payload):
    def create(**_kw):
        return types.SimpleNamespace(content=[types.SimpleNamespace(text=payload, type="text")])
    return types.SimpleNamespace(messages=types.SimpleNamespace(create=create))


def test_inspect_routes_anthropic_client_shape():
    payload = json.dumps({"verdicts": [{"cite": "X1", "supports_conclusion": "fail",
                                        "quote": "enters an order determining the result",
                                        "rationale": "overstated"}]})
    res = li.inspect("Under [[REF: X1]] we win.", {"X1"}, _resolver,
                     client=make_anthropic_stub(payload), model="claude-x")
    assert res["ok"] and res["verdicts"][0]["supports_conclusion"] == "fail"


def test_provider_and_default_model(monkeypatch):
    for k in ("HALLUCHECK_PROVIDER", "ANTHROPIC_API_KEY", "OPENAI_API_KEY",
              "HALLUCHECK_MODEL", "ANTHROPIC_MODEL"):
        monkeypatch.delenv(k, raising=False)
    assert li._provider() == "openai"
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    assert li._provider() == "anthropic"
    assert li._default_model().startswith("claude")
    monkeypatch.setenv("HALLUCHECK_PROVIDER", "openai")
    assert li._provider() == "openai"


# --- a "pass" needs a real, non-trivial grounded quote ---------------------- #
def test_pass_without_quote_is_downgraded():
    payload = json.dumps({"verdicts": [{"cite": "X1", "supports_conclusion": "pass",
                                        "quote": "", "rationale": "trust me"}]})
    res = li.inspect("[[REF: X1]]", {"X1"}, _resolver, client=make_stub(payload), model="m")
    assert res["verdicts"][0]["supports_conclusion"] == "unclear"


# --- multi-judge quorum ----------------------------------------------------- #
def test_aggregate_verdicts_is_fail_biased():
    runs = [[{"cite": "A", "supports_conclusion": "pass", "quote_grounded": True}],
            [{"cite": "A", "supports_conclusion": "pass", "quote_grounded": True}],
            [{"cite": "A", "supports_conclusion": "fail", "quote_grounded": True}]]
    agg = li.aggregate_verdicts(runs)
    assert agg[0]["supports_conclusion"] == "fail"      # any fail wins
    assert agg[0]["samples"] == 3 and agg[0]["agreement"] == 1


def test_aggregate_requires_unanimous_pass():
    runs = [[{"cite": "A", "supports_conclusion": "pass", "quote_grounded": True}],
            [{"cite": "A", "supports_conclusion": "unclear", "quote_grounded": False}]]
    assert li.aggregate_verdicts(runs)[0]["supports_conclusion"] == "unclear"


def make_cycle_stub(payloads):
    seq = list(payloads)

    def create(**_kw):
        p = seq.pop(0) if len(seq) > 1 else seq[0]
        msg = types.SimpleNamespace(content=p, reasoning_content="")
        return types.SimpleNamespace(choices=[types.SimpleNamespace(message=msg)])
    return types.SimpleNamespace(
        chat=types.SimpleNamespace(completions=types.SimpleNamespace(create=create)))


def test_inspect_consensus_one_fail_flips_result():
    q = "enters an order determining the result"
    p = json.dumps({"verdicts": [{"cite": "X1", "supports_conclusion": "pass", "quote": q}]})
    f = json.dumps({"verdicts": [{"cite": "X1", "supports_conclusion": "fail", "quote": q}]})
    res = li.inspect_consensus("[[REF: X1]]", {"X1"}, _resolver, samples=3,
                               client=make_cycle_stub([p, p, f]), model="m")
    assert res["consensus"]["samples"] == 3
    assert res["verdicts"][0]["supports_conclusion"] == "fail"
