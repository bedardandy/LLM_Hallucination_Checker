"""Offline demo: scan a draft for citation problems with the Maine adapter.

    python3 examples/demo.py
"""
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from adapters.maine.adapter import MaineProbateAdapter
from hallucheck import guard, scan

adapter = MaineProbateAdapter()
draft = ("Under [[REF: 18-C §3-401]] the petitioner has standing. The nominee has "
         "an absolute right to serve, see 18-C §3-203 and the made-up 18-C §9-999, "
         "per https://example.com/ruling.")

print("== scan report ==")
print(json.dumps({k: v for k, v in scan.report(draft, adapter, scope="DE-101").items()
                  if k in ("leaked", "unresolvable", "out_of_vocab", "fabricated_urls")},
                 indent=2))

print("\n== guard decision (offline, attested) ==")
res = guard.evaluate(draft, adapter, scope="DE-101")
print("block:", res["block"])
print("reason:", res["reason"])
print("attestation signed:", res["attestation"]["signed"],
      "input_sha256:", res["attestation"]["receipt"]["input_sha256"][:16] + "…")
