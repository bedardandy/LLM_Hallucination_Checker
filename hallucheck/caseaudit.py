"""Cross-check an adapter's bundled case metadata against CourtListener.

The bundled case law in an adapter is AI-annotated; this is an automated integrity
check that each case **exists** in CourtListener with **matching metadata** — the
citation resolves, the reporter/neutral citation appears in the matched case's
citation list, the decision year agrees, and the case names overlap. It flags
cases that don't resolve or whose metadata disagrees, for human review.

It does **NOT** verify holdings, subsequent history, or that a case is good law —
that requires reading the opinion (and a citator). A clean audit means "this
citation points at a real case with consistent metadata", nothing more.
"""
from __future__ import annotations

import re

from . import courtlistener

_STOP = {"in", "re", "the", "of", "estate", "matter", "guardianship", "and",
         "conservatorship", "adult", "v", "vs"}


def _tokens(name: str) -> set[str]:
    return {w for w in re.findall(r"[a-z]+", (name or "").lower())
            if w not in _STOP and len(w) > 2}


def _names_overlap(a: str, b: str) -> bool:
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return True                              # nothing distinctive to compare
    return bool(ta & tb)                         # a shared distinctive token is enough


def audit_case(case: dict, result: dict) -> list[str]:
    """Issues for one ``case`` (``{name, cite, year}``) given its CourtListener
    ``lookup`` ``result``. Empty == consistent."""
    if not result.get("found"):
        return ["did not resolve in CourtListener"]
    issues = []
    cite = case.get("cite")
    if cite and cite not in (result.get("citations") or []):
        issues.append(f"citation {cite!r} not in CL's list {result.get('citations')}")
    yr = str(case.get("year") or "")
    if yr and result.get("date") and not str(result["date"]).startswith(yr):
        issues.append(f"year mismatch: bundled {yr} vs CL {result.get('date')}")
    if not _names_overlap(case.get("name", ""), result.get("case_name", "")):
        issues.append(f"name differs: bundled {case.get('name')!r} vs "
                      f"CL {result.get('case_name')!r}")
    return issues


def audit_cases(cases: dict, *, lookup=None, token: str | None = None) -> dict:
    """Audit ``{id: {name, cite, year}}`` against CourtListener. ``lookup`` is
    injectable for tests (defaults to :func:`courtlistener.lookup`). Returns
    ``{total, with_issues, rows:[{id, cite, found, issues, ...}]}``."""
    lookup = lookup or courtlistener.lookup
    rows = []
    for cid, c in cases.items():
        res = lookup(c["cite"], token=token)
        rows.append({"id": cid, "cite": c.get("cite"), "name": c.get("name"),
                     "found": bool(res.get("found")), "cl_name": res.get("case_name"),
                     "cl_date": res.get("date"), "issues": audit_case(c, res)})
    return {"total": len(rows), "with_issues": sum(1 for r in rows if r["issues"]),
            "rows": rows}
