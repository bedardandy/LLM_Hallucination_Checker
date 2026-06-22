#!/usr/bin/env python3
"""Cross-check the Maine adapter's bundled case law against CourtListener (live).

Existence/metadata only — NOT holdings or good-law status. Set COURTLISTENER_TOKEN
to raise rate limits.

    python tools/verify_caselaw.py
"""
import json
import os
import pathlib
import sys

from hallucheck import caseaudit

DATA = pathlib.Path("adapters/maine/data/caselaw.json")


def main() -> int:
    cases = json.loads(DATA.read_text(encoding="utf-8"))["cases"]
    rep = caseaudit.audit_cases(cases, token=os.environ.get("COURTLISTENER_TOKEN"))
    print(f"audited {rep['total']} cases — {rep['with_issues']} with metadata issues "
          f"(existence/metadata only; NOT holdings)\n")
    for r in rep["rows"]:
        mark = "ok  " if not r["issues"] else "FLAG"
        print(f"[{mark}] {r['cite']:18} {r['name']}")
        for i in r["issues"]:
            print(f"         - {i}")
    return 1 if rep["with_issues"] else 0


if __name__ == "__main__":
    sys.exit(main())
