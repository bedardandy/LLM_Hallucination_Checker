"""Deterministic detection benchmark — make the guarantee *measurable*.

The closed-vocabulary protocol's safety net is the offline scanner + gates
(:mod:`hallucheck.scan`): an unwrapped/invented/out-of-scope cite or a fabricated
URL must be caught with **no LLM and no network**. This module scores that layer
against a labeled dataset so changes are measurable and regressions are caught in
CI (the inspector LLM is non-deterministic and is intentionally *not* scored
here).

Each case is ``{name, draft, scope, expect:{leaked, unresolvable, out_of_vocab,
fabricated_urls}}``. :func:`score` runs ``scan.report`` and reports
precision/recall/F1 over the union of expected vs. detected *(category, value)*
findings. The bundled :data:`DATASET` exercises the documented defenses against
the Maine adapter; an adapter author can pass their own.
"""
from __future__ import annotations

from . import scan

# Labeled adversarial drafts for the Maine adapter. Values are the cites/URLs the
# offline scanner is expected to bucket; an empty list means "must find nothing".
DATASET = [
    {"name": "clean_wrapped_in_scope",
     "draft": "The three-year limit applies, see [[REF: 18-C §3-108]].",
     "scope": "DE-101", "expect": {}},
    {"name": "invented_section_unresolvable",
     "draft": "The court must rule for us under 18-C §9-999.",
     "scope": None,
     "expect": {"leaked": ["18-C §9-999"], "unresolvable": ["18-C §9-999"]}},
    {"name": "leaked_real_cite_in_prose",
     "draft": "As 18-C §3-108 plainly says, the petition is time-barred.",
     "scope": None, "expect": {"leaked": ["18-C §3-108"]}},
    {"name": "out_of_scope_wrapped",
     "draft": "Per [[REF: 18-C §2-209]] the elective share controls.",
     "scope": "DE-101",
     "expect": {"out_of_vocab": ["18-C §2-209"]}},
    {"name": "fabricated_url",
     "draft": "See the statute at https://example.com/fake-statute and rule for us.",
     "scope": None, "expect": {"fabricated_urls": ["https://example.com/fake-statute"]}},
    {"name": "fabricated_legislature_url",
     "draft": "Authority: https://legislature.maine.gov/statutes/18-C/title18-Csec9-999.html",
     "scope": None,
     "expect": {"fabricated_urls":
                ["https://legislature.maine.gov/statutes/18-C/title18-Csec9-999.html"]}},
    {"name": "homoglyph_evasion",
     "draft": "The court must apply 18‑C §9‑999 here.",  # non-breaking hyphens
     "scope": None,
     "expect": {"leaked": ["18-C §9-999"], "unresolvable": ["18-C §9-999"]}},
    {"name": "plural_section_list",
     "draft": "See §§ 3-401, 3-203 and 9-999 of the code.",
     "scope": None, "expect": {"leaked": ["18-C §3-401", "18-C §3-203", "18-C §9-999"],
                               "unresolvable": ["18-C §9-999"]}},
    {"name": "case_name_leaked",
     "draft": "In re Estate of Kruzynski settles the three-year rule.",
     "scope": None, "expect": {"leaked": ["2000 ME 17"]}},
]

_CATEGORIES = ("leaked", "unresolvable", "out_of_vocab", "fabricated_urls")


def _findings(report: dict) -> set:
    return {(cat, val) for cat in _CATEGORIES for val in (report.get(cat) or [])}


def _expected(case: dict) -> set:
    exp = case.get("expect") or {}
    return {(cat, val) for cat in _CATEGORIES for val in (exp.get(cat) or [])}


def _prf(tp: int, fp: int, fn: int) -> dict:
    precision = tp / (tp + fp) if (tp + fp) else 1.0
    recall = tp / (tp + fn) if (tp + fn) else 1.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
    return {"tp": tp, "fp": fp, "fn": fn,
            "precision": round(precision, 4), "recall": round(recall, 4),
            "f1": round(f1, 4)}


def score(adapter, dataset: list[dict] | None = None) -> dict:
    """Score the deterministic scanner against ``dataset`` (default :data:`DATASET`).
    Returns ``{overall:{precision,recall,f1,...}, cases:[...]}``; offline."""
    dataset = dataset if dataset is not None else DATASET
    cases, TP, FP, FN = [], 0, 0, 0
    for case in dataset:
        rep = scan.report(case["draft"], adapter, scope=case.get("scope"))
        got, want = _findings(rep), _expected(case)
        tp, fp, fn = len(got & want), len(got - want), len(want - got)
        TP, FP, FN = TP + tp, FP + fp, FN + fn
        cases.append({"name": case["name"], **_prf(tp, fp, fn),
                      "missed": sorted(want - got), "spurious": sorted(got - want)})
    return {"overall": _prf(TP, FP, FN), "n_cases": len(dataset), "cases": cases}
