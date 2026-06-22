"""``hallucheck`` command-line interface.

    hallucheck emit-prompt --adapter maine --scope DE-101
    hallucheck inspect      --adapter maine --scope DE-101 --draft draft.txt --attest
    hallucheck scan         --adapter maine --scope DE-101 --draft draft.txt
    hallucheck links        --adapter maine --check
    hallucheck sources      --adapter maine --cite "2000 ME 17"
    hallucheck pack         --adapter maine --scope DE-101 --draft brief.txt \
                            --format pdf --out authorities.pdf
    hallucheck verify       receipt.json --input draft.txt
    hallucheck verify-log   inspection_log.jsonl
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

from . import adapter as _adapter
from . import attest, benchmark, courtlistener, embed, inspector, links, research, scan, sources


def _read(path_or_dash: str | None) -> str:
    if not path_or_dash or path_or_dash == "-":
        return sys.stdin.read()
    return pathlib.Path(path_or_dash).read_text(encoding="utf-8")


def _inspect_result(adapter, scope, text, samples=1):
    vocab = adapter.build_vocabulary(scope)
    resolver = lambda key: adapter.resolve(key, fetch_text=True)
    res = (inspector.inspect_consensus(text, set(vocab), resolver, samples=samples)
           if samples > 1 else inspector.inspect(text, set(vocab), resolver))
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
            sp.add_argument("--samples", type=int, default=1,
                            help="run the inspector N times and take a fail-biased consensus")
        if name == "links":
            sp.add_argument("--check", action="store_true")
            sp.add_argument("--scope-mode", default="used", choices=["used", "all"])
        sp.add_argument("--json", action="store_true")

    src = sub.add_parser("sources")
    src.add_argument("--adapter", required=True)
    src.add_argument("--cite", required=True)
    src.add_argument("--scope")
    src.add_argument("--json", action="store_true")

    pk = sub.add_parser("pack")
    pk.add_argument("--adapter", required=True)
    pk.add_argument("--scope")
    pk.add_argument("--draft", help="brief to extract citations from (file or '-')")
    pk.add_argument("--cite", action="append", default=[], help="add a citation (repeatable)")
    pk.add_argument("--format", default="md", choices=["md", "html", "docx", "pdf", "json"])
    pk.add_argument("--out", help="output file (required for docx/pdf)")
    pk.add_argument("--treatments", help="JSON file: {cite: {status, note, authorities}}")
    pk.add_argument("--title")
    pk.add_argument("--no-fetch", action="store_true",
                    help="offline: use the adapter's bundled text, don't fetch source URLs")
    pk.add_argument("--courtlistener", action="store_true",
                    help="network: attach the CourtListener opinion link/excerpt per case")
    pk.add_argument("--citing", type=int, default=0, metavar="N",
                    help="network: also attach the N most-recent citing opinions per case "
                         "for treatment review (implies --courtlistener)")
    pk.add_argument("--fetch-opinions", metavar="DIR",
                    help="network: download available opinion files into DIR and link them "
                         "(implies --courtlistener)")

    bn = sub.add_parser("bench")
    bn.add_argument("--adapter", required=True)
    bn.add_argument("--json", action="store_true")

    cl = sub.add_parser("cl-lookup")
    cl.add_argument("--cite", required=True)
    cl.add_argument("--citing", type=int, default=0, metavar="N",
                    help="also list the N most-recent citing opinions (treatment review)")
    cl.add_argument("--json", action="store_true")

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
    if a.cmd == "cl-lookup":
        import os
        token = os.environ.get("COURTLISTENER_TOKEN")
        res = courtlistener.lookup(a.cite, token=token)
        if res.get("found") and a.citing:
            res["citing"] = courtlistener.citing(res["opinion_id"], limit=a.citing, token=token)
        if a.json:
            print(json.dumps(res, indent=2, ensure_ascii=False))
        elif res.get("found"):
            print(f"{res['case_name']} — {res['court']}, {res['date']}")
            print(f"  citations: {', '.join(res['citations'])}")
            print(f"  opinion:   {res['absolute_url']}")
            if res.get("cite_count") is not None:
                print(f"  cited by ~{res['cite_count']} later opinion(s) — review for treatment")
            for o in (res.get("citing") or {}).get("opinions", []):
                print(f"    - {o.get('date') or ''}  {o.get('case_name')}  {o.get('absolute_url')}")
        else:
            print(f"not found: {a.cite}" + (f" ({res['error']})" if res.get("error") else ""))
        return 0 if res.get("found") else 1

    adapter = _adapter.load(a.adapter)

    if a.cmd == "emit-prompt":
        print(inspector.draft_system_prompt(adapter.build_vocabulary(a.scope)))
        return 0
    if a.cmd == "bench":
        rep = benchmark.score(adapter)
        if a.json:
            print(json.dumps(rep, indent=2, ensure_ascii=False))
        else:
            o = rep["overall"]
            print(f"deterministic detection [{rep['n_cases']} cases]: "
                  f"precision={o['precision']} recall={o['recall']} f1={o['f1']} "
                  f"(tp={o['tp']} fp={o['fp']} fn={o['fn']})")
            for c in rep["cases"]:
                flag = "" if not (c["missed"] or c["spurious"]) else "  <-- CHECK"
                print(f"  {c['name']:34} P={c['precision']} R={c['recall']}{flag}")
                if c["missed"]:
                    print(f"      missed:   {c['missed']}")
                if c["spurious"]:
                    print(f"      spurious: {c['spurious']}")
        return 1 if (rep["overall"]["fp"] or rep["overall"]["fn"]) else 0
    if a.cmd == "links":
        rep = links.audit(adapter, a.scope_mode)
        if a.json:
            print(json.dumps(rep, indent=2, ensure_ascii=False))
        else:
            print(f"link audit [{a.scope_mode}]: {rep['by_status']} ({rep['checked']} urls)")
            for u in rep["dead"]:
                print(f"  DEAD  {u}  (cites: {', '.join(rep['results'][u]['cites'])})")
        return 1 if rep["dead"] else 0

    if a.cmd == "sources":
        meta = adapter.build_vocabulary(a.scope).get(a.cite, {"cite": a.cite})
        rec = {"cite": a.cite, **{k: meta.get(k) for k in ("kind", "title", "url", "name")}}
        out = sources.for_citation(rec)
        if a.json:
            print(json.dumps(out, indent=2, ensure_ascii=False))
        else:
            print(f"sources for {a.cite} ({out['kind']}):")
            for ln in out["links"]:
                print(f"  [{ln['access']:8}] {ln['label']}: {ln.get('url') or ln.get('view_url')}")
            for p in out["portals"]:
                print(f"  [{p['access']:8}] {p['label']}: {p['portal_url']}  (login; search: {p['query']})")
        return 0
    if a.cmd == "pack":
        import os
        treatments = (json.loads(pathlib.Path(a.treatments).read_text(encoding="utf-8"))
                      if a.treatments else None)
        draft = _read(a.draft) if a.draft else None
        token = os.environ.get("COURTLISTENER_TOKEN")
        use_cl = a.courtlistener or bool(a.fetch_opinions) or a.citing > 0
        packet = research.build_packet(adapter, cites=a.cite or None, draft=draft,
                                       scope=a.scope, fetch_text=not a.no_fetch,
                                       treatments=treatments, title=a.title,
                                       courtlistener_lookup=use_cl, cl_token=token,
                                       cl_citing_limit=a.citing)
        if a.fetch_opinions:
            n = research.attach_opinions(packet, a.fetch_opinions, token=token)
            print(f"downloaded {n} opinion file(s) -> {a.fetch_opinions}", file=sys.stderr)
        if a.format == "json":
            payload = json.dumps(packet, indent=2, ensure_ascii=False)
            (pathlib.Path(a.out).write_text(payload, encoding="utf-8") if a.out else print(payload))
        else:
            rendered = embed.render(packet, a.format, path=a.out)
            if a.format in ("md", "html") and not a.out:
                print(rendered)
        if a.out:
            print(f"wrote {packet['counts']['total']} authorities -> {a.out}", file=sys.stderr)
        return 1 if packet["unverified"] else 0

    text = _read(a.draft)
    if a.cmd == "scan":
        rep = scan.report(text, adapter, scope=a.scope)
        print(json.dumps(rep, indent=2, ensure_ascii=False) if a.json else
              f"leaked={rep['leaked']} unresolvable={rep['unresolvable']} "
              f"fabricated_urls={rep['fabricated_urls']}")
        return 1 if (rep["leaked"] or rep["unresolvable"] or rep["fabricated_urls"]) else 0

    res = _inspect_result(adapter, a.scope, text, samples=getattr(a, "samples", 1))
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
