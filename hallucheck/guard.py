"""Shared guard core for harness integrations (hook + proxy).

:func:`evaluate` runs the deterministic scanner over model output and decides
whether to *block*: it fires on a leaked cite (outside the ``[[REF:]]`` protocol),
an unresolvable cite, or a fabricated URL. Offline by default — no LLM, no
network — which is what you want in a blocking hook. With ``llm=True`` it also runs
the inspector so a mischaracterization (``fail``), ``invented``, or ``dead_link``
contributes. Every evaluation is attested.
"""
from __future__ import annotations

from . import attest as _attest
from . import inspector, scan


def _reason(scan_rep: dict, result: dict) -> str:
    bits = []
    if scan_rep.get("leaked"):
        bits.append(f"citations outside the [[REF:]] protocol: {', '.join(scan_rep['leaked'])}")
    if scan_rep.get("unresolvable"):
        bits.append(f"citations not in the trusted index: {', '.join(scan_rep['unresolvable'])}")
    if scan_rep.get("out_of_vocab"):
        bits.append(f"citations outside the allowed scope: {', '.join(scan_rep['out_of_vocab'])}")
    if scan_rep.get("fabricated_urls"):
        bits.append(f"fabricated/placeholder URLs: {', '.join(scan_rep['fabricated_urls'])}")
    if result.get("invented"):
        bits.append(f"invented placeholder cites: {', '.join(result['invented'])}")
    if result.get("dead_links"):
        bits.append(f"dead authority links: {', '.join(result['dead_links'])}")
    if (result.get("summary") or {}).get("fail"):
        fails = [v["cite"] for v in result.get("verdicts", [])
                 if v.get("supports_conclusion") == "fail"]
        bits.append(f"conclusions unsupported by the cited source: {', '.join(fails)}")
    return "Hallucination guard blocked: " + "; ".join(bits) + "." if bits else ""


def evaluate(text: str, adapter, *, scope: str | None = None, llm: bool = False,
             attest: bool = True, log_path=None, model: str | None = None,
             require_protocol: bool = True) -> dict:
    """Return ``{block, reason, scan, attestation?}`` for a piece of model output.

    Blocks on an unresolvable cite, an out-of-scope cite, or a fabricated URL —
    always. With ``require_protocol`` (default) it also blocks on any *leaked*
    citation (one written outside a ``[[REF:]]`` placeholder), since an unwrapped
    cite is never substituted or inspected and so can't be verified; set
    ``require_protocol=False`` to allow bare prose citations."""
    scan_rep = scan.report(text or "", adapter, scope=scope)
    result = {"ok": True, "scope": scope, "scan": scan_rep, "verdicts": [],
              "summary": {"fail": 0, "unresolved": 0, "dead_links": 0, "invented": 0}}
    if llm:
        vocab = adapter.build_vocabulary(scope)
        ins = inspector.inspect(text or "", set(vocab),
                                adapter_resolver(adapter), model=model)
        ins["scan"] = scan_rep
        result = ins
        result["scope"] = scope

    block = bool(scan_rep.get("unresolvable") or scan_rep.get("out_of_vocab")
                 or scan_rep.get("fabricated_urls"))
    if require_protocol:
        block = block or bool(scan_rep.get("leaked"))
    if llm:
        s = result.get("summary") or {}
        block = block or s.get("fail", 0) > 0 or bool(result.get("invented")) \
            or bool(result.get("dead_links"))

    out = {"block": block, "reason": _reason(scan_rep, result) if block else "",
           "scan": scan_rep}
    if attest:
        out["attestation"] = _attest.record_inspection(
            text or "", result, tool="hallucheck-guard",
            config_digest=_safe_digest(adapter), log_path=log_path)
    return out


def adapter_resolver(adapter):
    return lambda key: adapter.resolve(key, fetch_text=True)


def _safe_digest(adapter) -> str | None:
    try:
        return adapter.config_digest()
    except Exception:
        return None
