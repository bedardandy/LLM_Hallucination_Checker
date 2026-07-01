"""Tamper-evident attestation that the inspector actually ran.

A guard you can't prove ran is only as trustworthy as the operator's word. Emits a
signed, independently-verifiable *receipt* per inspection and chains receipts into
an append-only log, so you can prove: (a) it ran, (b) on this exact input, (c)
with nothing suppressed, and (d) let anyone re-check.

The signing key (``$ATTEST_HMAC_KEY``) is operator-held, NOT the agent's, so a
model can't forge "it passed". Without a key the receipt is still produced and
chained (a record), flagged ``signed: false``. The deterministic findings are
reproducible; the LLM verdict is covered by the signed ``verdict_digest``. A
receipt proves the inspector ran and what it found — only a fail-closed gate
proves the agent heeded a failure.
"""
from __future__ import annotations

import datetime
import hashlib
import hmac
import json
import os
import pathlib
import platform
import secrets
from collections.abc import Iterable
from importlib import metadata

SCHEMA = "llm-hallucination-attestation/v2"
GENESIS = "0" * 64


def canonical(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_text(s: str) -> str:
    return hashlib.sha256((s or "").encode("utf-8")).hexdigest()


def sha256_file(path, *, chunk_size: int = 1024 * 1024) -> str:
    """Return the SHA-256 digest for a file without loading it all into memory."""
    h = hashlib.sha256()
    with pathlib.Path(path).open("rb") as fh:
        for chunk in iter(lambda: fh.read(chunk_size), b""):
            h.update(chunk)
    return h.hexdigest()


def make_source_manifest(sources: Iterable[str | os.PathLike | dict] | None) -> list[dict]:
    """Build a deterministic manifest for evidence/source files bound to a receipt.

    ``sources`` may be paths, or precomputed manifest dictionaries containing at
    least ``path`` and ``sha256``.  Paths are recorded exactly as supplied (so the
    receipt preserves operator intent) plus byte size and SHA-256 for later
    verification.
    """
    manifest: list[dict] = []
    for src in sources or []:
        if isinstance(src, dict):
            rec = {k: src[k] for k in sorted(src)}
            if "path" not in rec or "sha256" not in rec:
                raise ValueError("source manifest dicts must include path and sha256")
            manifest.append(rec)
            continue
        p = pathlib.Path(src)
        stat = p.stat()
        manifest.append({"path": str(src), "size": stat.st_size, "sha256": sha256_file(p)})
    return manifest


def _tool_version() -> str | None:
    try:
        return metadata.version("llm-hallucination-checker")
    except metadata.PackageNotFoundError:
        return None


def _findings(result: dict) -> dict:
    scan = result.get("scan") or {}
    summ = result.get("summary") or {}
    return {
        "fail": summ.get("fail", 0),
        "invented": result.get("invented", []),
        "unresolved": result.get("unresolved", []),
        "dead_links": result.get("dead_links", []),
        "leaked": scan.get("leaked", []),
        "fabricated_urls": scan.get("fabricated_urls", []),
        "out_of_vocab": scan.get("out_of_vocab", []),
        "unclassified_citations": scan.get("unclassified_citations", []),
    }


def needs_review(result: dict) -> bool:
    f = _findings(result)
    return (not result.get("ok", True)) or f["fail"] > 0 or any(
        f[k] for k in ("invented", "unresolved", "dead_links", "leaked", "fabricated_urls",
                       "unclassified_citations"))


def make_receipt(input_text: str, result: dict, *, tool: str = "hallucheck",
                 model: str | None = None, config_digest: str | None = None,
                 sources: Iterable[str | os.PathLike | dict] | None = None) -> dict:
    source_manifest = make_source_manifest(sources)
    return {
        "schema": SCHEMA,
        "tool": tool,
        "tool_version": _tool_version(),
        "runtime": {"python": platform.python_version()},
        "config_digest": config_digest,
        "model": model or result.get("model"),
        "scope": result.get("scope") or result.get("form_id"),
        "input_sha256": sha256_text(input_text),
        "sources": source_manifest,
        "sources_digest": sha256_text(canonical(source_manifest)),
        "summary": result.get("summary"),
        "findings": _findings(result),
        "verdict_digest": sha256_text(canonical(result.get("verdicts", []))),
        "needs_review": needs_review(result),
        "ok": result.get("ok", True),
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "nonce": secrets.token_hex(16),
    }


def _key(key=None) -> bytes | None:
    if key is not None:
        return key if isinstance(key, bytes) else key.encode("utf-8")
    env = os.environ.get("ATTEST_HMAC_KEY")
    return env.encode("utf-8") if env else None


def sign_receipt(receipt: dict, *, key=None) -> dict:
    k, payload = _key(key), canonical(receipt)
    if k:
        sig = hmac.new(k, payload.encode("utf-8"), hashlib.sha256).hexdigest()
        return {"receipt": receipt, "alg": "HMAC-SHA256", "signature": sig, "signed": True}
    return {"receipt": receipt, "alg": "none", "signature": sha256_text(payload), "signed": False}


def _verify_sources(receipt: dict, sources: Iterable[str | os.PathLike] | None):
    expected = receipt.get("sources") or []
    if sha256_text(canonical(expected)) != receipt.get("sources_digest"):
        return False, "sources_digest mismatch"
    if sources is None:
        return True, "ok"
    supplied = list(sources)
    if len(supplied) != len(expected):
        return False, f"source count mismatch (receipt has {len(expected)}, got {len(supplied)})"
    for i, rec in enumerate(expected):
        path = pathlib.Path(supplied[i])
        try:
            actual = sha256_file(path)
        except OSError as exc:
            return False, f"source {i} unavailable ({path}): {exc}"
        if actual != rec.get("sha256"):
            return False, f"source {i} hash mismatch ({path})"
    return True, "ok"


def verify_receipt(signed: dict, *, key=None, input_text: str | None = None,
                   sources: Iterable[str | os.PathLike] | None = None):
    receipt = signed.get("receipt", {})
    payload = canonical(receipt)
    if signed.get("signed"):
        k = _key(key)
        if not k:
            return False, "receipt is signed but no key ($ATTEST_HMAC_KEY) to verify"
        expect = hmac.new(k, payload.encode("utf-8"), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expect, signed.get("signature", "")):
            return False, "signature mismatch (tampered or wrong key)"
    elif sha256_text(payload) != signed.get("signature"):
        return False, "content hash mismatch (unsigned receipt was altered)"
    if input_text is not None and sha256_text(input_text) != receipt.get("input_sha256"):
        return False, "input does not match receipt.input_sha256"
    ok, detail = _verify_sources(receipt, sources)
    if not ok:
        return ok, detail
    return True, "ok"


def _hash_line(line: str) -> str:
    return hashlib.sha256(line.encode("utf-8")).hexdigest()


def append_log(signed: dict, log_path) -> dict:
    p = pathlib.Path(log_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    prev_hash, seq = GENESIS, 0
    if p.exists():
        lines = [ln for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip()]
        if lines:
            prev_hash = _hash_line(lines[-1])
            seq = json.loads(lines[-1]).get("seq", len(lines) - 1) + 1
    entry = {"seq": seq,
             "time": datetime.datetime.now(datetime.timezone.utc).isoformat(),
             "prev_hash": prev_hash,
             "receipt_hash": sha256_text(canonical(signed["receipt"])),
             "signed": signed}
    with p.open("a", encoding="utf-8") as fh:
        fh.write(canonical(entry) + "\n")
    return entry


def verify_log(log_path, *, key=None):
    p = pathlib.Path(log_path)
    if not p.exists():
        return False, [f"no log at {p}"]
    problems, prev_hash = [], GENESIS
    lines = [ln for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip()]
    for i, ln in enumerate(lines):
        try:
            entry = json.loads(ln)
        except Exception as e:
            problems.append(f"entry {i}: not JSON ({e})")
            prev_hash = _hash_line(ln)
            continue
        if entry.get("seq") != i:
            problems.append(f"entry {i}: seq mismatch ({entry.get('seq')})")
        if entry.get("prev_hash") != prev_hash:
            problems.append(f"entry {i} (seq {entry.get('seq')}): chain break")
        ok, detail = verify_receipt(entry.get("signed", {}), key=key, sources=None)
        if not ok:
            problems.append(f"entry {i}: {detail}")
        if sha256_text(canonical(entry.get("signed", {}).get("receipt", {}))) != entry.get("receipt_hash"):
            problems.append(f"entry {i}: receipt_hash mismatch")
        prev_hash = _hash_line(ln)
    return (not problems), problems


def record_inspection(input_text: str, result: dict, *, tool: str = "hallucheck",
                      model: str | None = None, config_digest: str | None = None,
                      log_path=None, key=None,
                      sources: Iterable[str | os.PathLike | dict] | None = None) -> dict:
    signed = sign_receipt(make_receipt(input_text, result, tool=tool, model=model,
                                       config_digest=config_digest, sources=sources), key=key)
    log_path = log_path or os.environ.get("ATTEST_LOG") or None
    if log_path:
        entry = append_log(signed, log_path)
        signed["log"] = {"seq": entry["seq"], "path": str(log_path)}
    return signed
