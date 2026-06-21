"""``hallucheck`` command-line interface.

    hallucheck emit-prompt --adapter maine --scope DE-101
    hallucheck inspect      --adapter maine --scope DE-101 --draft draft.txt --attest
    hallucheck scan         --adapter maine --scope DE-101 --draft draft.txt
    hallucheck links        --adapter maine --check
    hallucheck verify       receipt.json --input draft.txt
    hallucheck verify-log   inspection_log.jsonl
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

from . import adapter as _adapter
from . import attest, inspector, links, scan


def _read(path_or_dash: str | None) -> str:
    if not path_or_dash or path_or_dash == "-":
        return sys.stdin.read()
    return pathlib.Path(path_or_dash).read_text(encoding="utf-8")


def _inspect_result(adapter, scope, text):
    vocab = adapter.build_vocabulary(scope)
    resolver = lambda key: adapter.resolve(key, fetch_text=True)
    res = inspector.inspect(text, set(vocab), resolver)
    res["scope"] = scope
    res["scan"] = scan.report(text, adapter, scope=scope)
    res["disclaimer"] = getattr(adapter, "disclaimer", "")
    return res


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="hallucheck", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("emit-prompt", "inspect", "scan", "links"):
        sp = sub.add_parser(name)
        sp.add_argument("--adapter", required=True)
        sp.add_argument("--scope")
        if name in ("inspect", "scan"):
            sp.add_argument("--draft")
        if name == "inspect":
            sp.add_argument("--attest", action="store_true")
            sp.add_argument("--log")
        if name == "links":
            sp.add_argument("--check", action="store_true")
            sp.add_argument("--scope-mode", default="used", choices=["used", "all"])
        sp.add_argument("--json", action="store_true")
    v = sub.add_parser("verify"); v.add_argument("receipt"); v.add_argument("--input")
    vl = sub.add_parser("verify-log"); vl.add_argument("log")
    a = ap.parse_args(argv)

    if a.cmd == "verify":
        signed = json.loads(pathlib.Path(a.receipt).read_text(encoding="utf-8"))
        intext = _read(a.input) if a.input else None
        ok, detail = attest.verify_receipt(signed, input_text=intext)
        print(f"{'OK' if ok else 'FAIL'} — {detail}")
        return 0 if ok else 1
    if a.cmd == "verify-log":
        ok, problems = attest.verify_log(a.log)
        print("OK — log chain intact" if ok else f"FAIL — {len(problems)} problem(s)")
        for p in problems:
            print("  - " + p, file=sys.stderr)
        return 0 if ok else 1

    adapter = _adapter.load(a.adapter)

    if a.cmd == "emit-prompt":
        print(inspector.draft_system_prompt(adapter.build_vocabulary(a.scope)))
        return 0
    if a.cmd == "links":
        rep = links.audit(adapter, a.scope_mode)
        if a.json:
            print(json.dumps(rep, indent=2, ensure_ascii=False))
        else:
            print(f"link audit [{a.scope_mode}]: {rep['by_status']} ({rep['checked']} urls)")
            for u in rep["dead"]:
                print(f"  DEAD  {u}  (cites: {', '.join(rep['results'][u]['cites'])})")
        return 1 if rep["dead"] else 0

    text = _read(a.draft)
    if a.cmd == "scan":
        rep = scan.report(text, adapter, scope=a.scope)
        print(json.dumps(rep, indent=2, ensure_ascii=False) if a.json else
              f"leaked={rep['leaked']} unresolvable={rep['unresolvable']} "
              f"fabricated_urls={rep['fabricated_urls']}")
        return 1 if (rep["leaked"] or rep["unresolvable"] or rep["fabricated_urls"]) else 0

    res = _inspect_result(adapter, a.scope, text)
    if a.attest or a.log:
        res["attestation"] = attest.record_inspection(
            text, res, config_digest=_safe_digest(adapter), log_path=a.log)
    print(json.dumps(res, indent=2, ensure_ascii=False) if a.json else _scorecard(res))
    return 1 if attest.needs_review(res) else 0


def _safe_digest(adapter):
    try:
        return adapter.config_digest()
    except Exception:
        return None


def _scorecard(res: dict) -> str:
    s, scan_rep = res.get("summary", {}), res.get("scan", {})
    lines = [f"inspection [{res.get('scope')}]  pass={s.get('pass',0)} fail={s.get('fail',0)} "
             f"unclear={s.get('unclear',0)} unresolved={s.get('unresolved',0)} "
             f"dead_links={s.get('dead_links',0)} invented={s.get('invented',0)}"]
    for label, vals in (("INVENTED", res.get("invented")), ("DEAD LINK", res.get("dead_links")),
                        ("LEAKED", scan_rep.get("leaked")),
                        ("UNRESOLVABLE", scan_rep.get("unresolvable")),
                        ("FABRICATED URL", scan_rep.get("fabricated_urls"))):
        if vals:
            lines.append(f"  {label}: {', '.join(vals)}")
    for v in res.get("verdicts", []):
        mark = {"pass": "PASS", "fail": "FAIL", "unclear": "????"}.get(v["supports_conclusion"])
        gq = "" if v.get("quote_grounded", True) else "  [quote NOT in source]"
        lines.append(f"  {mark}  {v.get('cite')}{gq}")
    if not res.get("ok"):
        lines.append(f"  [warning] inspector LLM unavailable: {res.get('error')}")
    if res.get("attestation"):
        att = res["attestation"]
        lines.append(f"  attestation: signed={att.get('signed')} "
                     f"input_sha256={att['receipt']['input_sha256'][:16]}…")
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
