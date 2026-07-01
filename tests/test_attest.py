"""Attestation tests — signing, tamper detection, hash-chained log, binding."""
import json

from adapters.maine.adapter import MaineProbateAdapter
from hallucheck import attest, guard

_RESULT = {
    "ok": True, "scope": "DE-101",
    "summary": {"fail": 1, "unresolved": 0, "dead_links": 0, "invented": 1},
    "invented": ["Made_Up"], "unresolved": [], "dead_links": [],
    "verdicts": [{"cite": "18-C §3-401", "supports_conclusion": "fail"}],
    "scan": {"leaked": ["18-C §3-203"], "unresolvable": [], "fabricated_urls": []},
}


def test_receipt_binds_input_and_findings():
    r = attest.make_receipt("draft text", _RESULT, config_digest="abc")
    assert r["input_sha256"] == attest.sha256_text("draft text")
    assert r["needs_review"] is True and r["config_digest"] == "abc"


def test_sign_verify_and_tamper():
    key = b"secret"
    signed = attest.sign_receipt(attest.make_receipt("d", _RESULT), key=key)
    assert attest.verify_receipt(signed, key=key)[0]
    signed["receipt"]["needs_review"] = False              # forge "it passed"
    ok, detail = attest.verify_receipt(signed, key=key)
    assert not ok and "mismatch" in detail


def test_input_binding():
    key = b"k"
    signed = attest.sign_receipt(attest.make_receipt("the draft", _RESULT), key=key)
    assert attest.verify_receipt(signed, key=key, input_text="the draft")[0]
    assert not attest.verify_receipt(signed, key=key, input_text="other")[0]


def test_unsigned_is_tamper_evident():
    signed = attest.sign_receipt(attest.make_receipt("d", _RESULT))
    assert signed["signed"] is False and attest.verify_receipt(signed)[0]
    signed["receipt"]["ok"] = False
    assert not attest.verify_receipt(signed)[0]


def test_log_chain(tmp_path, monkeypatch):
    monkeypatch.setenv("ATTEST_HMAC_KEY", "secret")
    log = tmp_path / "log.jsonl"
    for t in ("a", "b", "c"):
        attest.record_inspection(t, _RESULT, log_path=str(log))
    assert attest.verify_log(str(log))[0]
    lines = log.read_text().splitlines()
    e = json.loads(lines[1]); e["signed"]["receipt"]["ok"] = False
    lines[1] = attest.canonical(e); log.write_text("\n".join(lines) + "\n")
    ok, problems = attest.verify_log(str(log))
    assert not ok and problems


def test_guard_blocks_and_attests(tmp_path):
    res = guard.evaluate("rely on https://example.com/x and 18-C §9-999",
                         MaineProbateAdapter(), log_path=str(tmp_path / "g.jsonl"))
    assert res["block"] is True
    assert res["attestation"]["receipt"]["tool"] == "hallucheck-guard"
    assert (tmp_path / "g.jsonl").exists()


def test_guard_allows_clean_text():
    res = guard.evaluate("A plain sentence with no citations.",
                         MaineProbateAdapter(), attest=False)
    assert res["block"] is False


def test_receipt_binds_source_manifest_and_detects_source_tamper(tmp_path):
    src = tmp_path / "authority.txt"
    src.write_text("verified authority text", encoding="utf-8")
    signed = attest.sign_receipt(attest.make_receipt("draft", _RESULT, sources=[src]), key=b"k")

    receipt = signed["receipt"]
    assert receipt["sources"][0]["sha256"] == attest.sha256_file(src)
    assert receipt["sources_digest"] == attest.sha256_text(attest.canonical(receipt["sources"]))
    assert attest.verify_receipt(signed, key=b"k", sources=[src])[0]

    src.write_text("altered authority text", encoding="utf-8")
    ok, detail = attest.verify_receipt(signed, key=b"k", sources=[src])
    assert not ok and "source 0 hash mismatch" in detail


def test_log_chain_detects_seq_reorder(tmp_path, monkeypatch):
    monkeypatch.setenv("ATTEST_HMAC_KEY", "secret")
    log = tmp_path / "seq.jsonl"
    for t in ("a", "b"):
        attest.record_inspection(t, _RESULT, log_path=str(log))
    lines = log.read_text(encoding="utf-8").splitlines()
    entry = json.loads(lines[1])
    entry["seq"] = 7
    lines[1] = attest.canonical(entry)
    log.write_text("\n".join(lines) + "\n", encoding="utf-8")
    ok, problems = attest.verify_log(str(log))
    assert not ok
    assert any("seq mismatch" in p for p in problems)
