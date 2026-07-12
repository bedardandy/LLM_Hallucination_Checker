"""Adversarial authority-use review helpers.

This module does not decide legal correctness.  It builds deterministic review
workflows around a cited authority: where the draft relies on it, what textual
support is visible, which leaps/overstatements deserve scrutiny, and what
counter-treatment or legislative-history searches a reviewer should run.
"""
from __future__ import annotations

import re

_STRONG_WORDS = {"always", "never", "must", "required", "automatically", "clearly",
                 "settled", "dispositive", "controls", "forecloses", "precludes"}
_LIMITING_WORDS = {"however", "except", "unless", "provided", "but", "although",
                   "distinguish", "limited", "narrow", "not decide", "decline"}
_NEGATIVE_TREATMENT = ("overruled", "abrogated", "superseded", "distinguished",
                       "criticized", "limited", "questioned", "not followed")
_LEGIS_HISTORY = ("legislative history", "committee amendment", "committee report",
                  "statement of fact", "bill analysis", "session law", "public law",
                  "revisor's report", "floor debate")


def sentence_contexts(draft: str, entry: dict, *, window: int = 0) -> list[str]:
    """Sentences in ``draft`` that appear to rely on an authority entry."""
    if not draft:
        return []
    sentences = _sentences(draft)
    needles = _needles(entry)
    out: list[str] = []
    for i, sentence in enumerate(sentences):
        low = sentence.lower()
        if any(n and n in low for n in needles):
            start, end = max(0, i - window), min(len(sentences), i + window + 1)
            ctx = " ".join(sentences[start:end]).strip()
            if ctx not in out:
                out.append(ctx)
    return out


def analyze_authority_use(entry: dict, *, claim: str | None = None,
                          draft: str | None = None) -> dict:
    """Build a deterministic adversarial review plan for one authority entry."""
    contexts = [claim] if claim else sentence_contexts(draft or "", entry)
    contexts = [c for c in contexts if c]
    authority = entry.get("text") or ""
    text_low = authority.lower()
    ctx_text = " ".join(contexts)
    ctx_low = ctx_text.lower()
    warnings: list[dict] = []

    if not authority:
        warnings.append({"kind": "missing_authority_text",
                         "message": "No authority text is available; verify the source before assessing the claim."})
    if not contexts:
        warnings.append({"kind": "no_claim_context",
                         "message": "No draft sentence was linked to this authority; review all uses manually."})

    strong = sorted(w for w in _STRONG_WORDS if re.search(rf"\b{re.escape(w)}\b", ctx_low))
    if strong:
        warnings.append({"kind": "overstatement_risk", "terms": strong,
                         "message": "Draft uses strong/mandatory language; confirm the authority is that categorical."})

    limiting = sorted(w for w in _LIMITING_WORDS if w in text_low)
    if limiting and not any(w in ctx_low for w in limiting):
        warnings.append({"kind": "limiting_language_not_reflected", "terms": limiting[:8],
                         "message": "Authority contains limiting language that is not visible in the claim context."})

    unsupported = unsupported_terms(ctx_text, authority)
    if unsupported:
        warnings.append({"kind": "terms_not_found_in_authority", "terms": unsupported[:12],
                         "message": "Important claim terms do not appear in the authority text; check for paraphrase or leap."})

    return {
        "cite": entry.get("cite"),
        "title": entry.get("title") or entry.get("name"),
        "claim_contexts": contexts,
        "authority_sha256": entry.get("text_sha256"),
        "warnings": warnings,
        "adversarial_questions": adversarial_questions(entry, contexts),
        "counter_treatment_queries": treatment_queries(entry),
        "legislative_history_queries": legislative_history_queries(entry),
        "logical_leap_checks": logical_leap_checks(entry, contexts),
    }


def unsupported_terms(claim: str, authority: str) -> list[str]:
    """Significant words in the claim that are absent from the authority text."""
    authority_words = set(_words(authority))
    out = []
    for word in _words(claim):
        if len(word) < 5 or word in authority_words or word in _STOP:
            continue
        if word not in out:
            out.append(word)
    return out


def adversarial_questions(entry: dict, contexts: list[str] | None = None) -> list[str]:
    cite = entry.get("cite") or "this authority"
    return [
        f"What is the narrowest holding or operative rule of {cite}, stated without extrapolation?",
        f"Which exact words in {cite} support each material proposition in the claim?",
        f"What facts, procedural posture, or statutory version would distinguish {cite}?",
        f"Does the draft treat dicta, background, a summary, or a parenthetical as a holding of {cite}?",
        f"What would an opposing lawyer quote from {cite} to weaken this interpretation?",
        f"Has {cite} been overruled, abrogated, superseded, limited, questioned, or distinguished?",
    ]


def logical_leap_checks(entry: dict, contexts: list[str] | None = None) -> list[dict]:
    cite = entry.get("cite") or "the authority"
    checks = [
        ("holding_vs_dicta", f"Separate the binding holding of {cite} from dicta or explanatory language."),
        ("facts_match", "List the legally material facts in the authority and compare them to the draft's facts."),
        ("procedural_posture", "Check whether the result depends on standard of review, burden, waiver, or posture."),
        ("scope_creep", "Identify any move from a narrow rule to a broad categorical proposition."),
        ("missing_elements", "Break the asserted rule into elements and verify each element appears in the source."),
        ("contrary_authority", "Search for later or higher authority reaching the opposite result."),
    ]
    if (entry.get("kind") or "").lower() in {"statute", "crossref"}:
        checks.append(("statutory_version", "Confirm the effective date/version and whether amendments changed the text."))
    return [{"kind": k, "prompt": p} for k, p in checks]


def treatment_queries(entry: dict) -> list[str]:
    cite = entry.get("cite") or ""
    title = entry.get("title") or entry.get("name") or ""
    bits = [b for b in (cite, title) if b]
    queries = []
    for bit in bits:
        quoted = f'"{bit}"'
        queries.extend(f"{quoted} {term}" for term in _NEGATIVE_TREATMENT)
    if cite:
        queries.append(f'"{cite}" "negative treatment"')
        queries.append(f'"{cite}" "cited by"')
    return _dedupe(queries)


def legislative_history_queries(entry: dict) -> list[str]:
    """Search strings for statutory/rule history and amendment provenance."""
    cite = entry.get("cite") or ""
    title = entry.get("title") or entry.get("name") or ""
    kind = (entry.get("kind") or "").lower()
    if kind not in {"statute", "crossref", "rule", "regulation", "administrative_code"} and "§" not in cite:
        return []
    base = [b for b in (cite, title) if b]
    queries = []
    for bit in base:
        quoted = f'"{bit}"'
        queries.extend(f"{quoted} {term}" for term in _LEGIS_HISTORY)
    section = re.search(r"§\s*([\w.-]+)", cite)
    if section:
        queries.append(f'"{section.group(1)}" "effective date" amendment')
        queries.append(f'"{section.group(1)}" "prior law"')
    return _dedupe(queries)


def _needles(entry: dict) -> list[str]:
    vals = [entry.get("cite"), entry.get("title"), entry.get("name")]
    out: list[str] = []
    for v in vals:
        v = (v or "").strip().lower()
        if v:
            out.append(v)
        if v.lower().startswith("in re "):
            out.append(v[6:])
    return out


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text or "") if s.strip()]


def _words(text: str) -> list[str]:
    return [w.lower() for w in re.findall(r"[A-Za-z][A-Za-z'-]+", text or "")]


def _dedupe(items: list[str]) -> list[str]:
    return list(dict.fromkeys(items))


_STOP = {"about", "above", "after", "again", "against", "being", "below", "between",
         "could", "every", "from", "have", "into", "only", "other", "their", "there",
         "these", "those", "under", "where", "which", "while", "would", "court", "case",
         "claim", "authority", "statute", "section"}
