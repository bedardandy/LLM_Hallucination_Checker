"""Generic, closed-vocabulary citation hallucination inspector.

Provider- and corpus-agnostic core. Never let an LLM draft authority text from
memory: force it to cite only by emitting ``[[REF: KEY]]`` placeholders whose KEY
must come from a supplied allow-list. Substitute each placeholder with the *real*
authority text, then run a separate cold-eyes inspector LLM that checks, per
citation, whether the draft's conclusion is supported by that text.

Two hard-fail gates make an invented citation impossible to pass silently:
  Gate A (substitute): a KEY not in the closed vocabulary -> ``invented`` (no LLM).
  Gate B (resolve):    an in-vocab KEY whose authority text can't be resolved ->
                       ``unresolved`` (distinct from "dead_link" when the adapter
                       flags a 404 authority URL).

The inspector LLM uses any OpenAI-compatible endpoint
(``HALLUCHECK_BASE_URL`` / ``HALLUCHECK_MODEL`` / ``HALLUCHECK_API_KEY``, falling
back to ``OPENAI_*``), temperature 0, JSON-validated, retried. Opt-in and
non-deterministic — never wire it into a deterministic output path.
"""
from __future__ import annotations

import json
import os
import re
from collections.abc import Callable

PLACEHOLDER = re.compile(r"\[\[REF:\s*(?P<key>[^\]]+?)\s*\]\]")
_VERDICTS = {"pass", "fail", "unclear"}
MIN_QUOTE_CHARS = 8          # a "pass" must rest on a non-trivial grounded quote

DRAFT_SYSTEM_HEADER = (
    "You are a drafting assistant. Draft the requested analysis, but you are "
    "STRICTLY FORBIDDEN from writing out the text of any cited source from memory. "
    "Whenever you rely on a source you MUST cite it ONLY by emitting a placeholder "
    "of the exact form [[REF: KEY]], copying the KEY verbatim from the ALLOWED "
    "CITATIONS list below. You may use ONLY keys from that list. If no listed "
    "source fits, say so in plain words — do NOT invent a key, a citation, or "
    "source text. The exact source text is filled in from a verified database."
)

INSPECT_SYSTEM = (
    "You are a senior hallucination inspector. You are given a draft in which every "
    "citation has been replaced with the VERBATIM text of the cited source, inside "
    "blocks delimited by lines '=== AUTHORITY [cite] ===' and '=== END [cite] ==='. "
    "For EACH block, judge ONLY against the literal text shown (use no outside "
    "knowledge) whether the draft's conclusions relying on it are supported. "
    "Respond with ONLY compact JSON: {\"verdicts\":[{\"cite\":\"<bracketed cite>\","
    "\"supports_conclusion\":\"pass|fail|unclear\",\"quote\":\"<exact span copied "
    "verbatim from the authority>\",\"rationale\":\"<one sentence>\"}]}. 'pass' = "
    "the source supports the draft's use of it; 'fail' = the draft mischaracterizes "
    "or overstates it; 'unclear' = the text is insufficient. 'quote' MUST be copied "
    "verbatim from inside the block, never paraphrased."
)


def _extract_json(text: str) -> dict:
    """Return the last valid top-level JSON object in ``text`` (robust to prose
    and reasoning tokens around it)."""
    text = text or ""
    decoder = json.JSONDecoder()
    candidates = []
    for i, ch in enumerate(text):
        if ch != "{":
            continue
        try:
            value, length = decoder.raw_decode(text[i:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            candidates.append((i + length, -i, value))
    return max(candidates, key=lambda it: (it[0], it[1]))[2] if candidates else {}


def extract_refs(draft: str) -> list[str]:
    seen: dict[str, None] = {}
    for m in PLACEHOLDER.finditer(draft or ""):
        seen.setdefault(m.group("key").strip(), None)
    return list(seen)


def draft_system_prompt(vocabulary: dict) -> str:
    """Closed-vocabulary draft-generator prompt. ``vocabulary`` maps KEY -> meta;
    keys are enumerated so the model can cite only by copying one."""
    lines = []
    for key, meta in vocabulary.items():
        label = (meta.get("title") or meta.get("name") or "") if isinstance(meta, dict) else ""
        lines.append(f"  [[REF: {key}]]  {label}".rstrip())
    return DRAFT_SYSTEM_HEADER + "\n\nALLOWED CITATIONS:\n" + "\n".join(lines)


def substitute(draft: str, vocabulary, resolver: Callable[[str], dict | None]):
    """Replace each ``[[REF: KEY]]`` with the cited authority text (``re.sub`` over
    captured spans). Returns ``(text, citations)`` with a per-cite ``status`` of
    resolved / unresolved / dead_link / invented."""
    vocabulary = set(vocabulary)
    citations: list[dict] = []
    index: dict[str, dict] = {}

    def _block(rec: dict) -> str:
        cite = rec.get("cite", rec["key"])
        if rec["status"] == "resolved":
            head = f"\n=== AUTHORITY [{cite}] ===\n"
            if rec.get("title"):
                head += f"Title: {rec['title']}\n"
            return head + rec["text"].strip() + f"\n=== END [{cite}] ===\n"
        if rec["status"] == "dead_link":
            return f"[[DEAD LINK: {rec['key']}]]"
        if rec["status"] == "unresolved":
            return f"[[UNRESOLVED: {rec['key']}]]"
        return f"[[INVENTED: {rec['key']}]]"

    def _repl(m: re.Match) -> str:
        key = m.group("key").strip()
        rec = index.get(key)
        if rec is None:
            if key not in vocabulary:                 # Gate A
                rec = {"key": key, "status": "invented"}
            else:
                try:
                    auth = resolver(key)
                except Exception as exc:
                    auth, rec = None, {"key": key, "status": "unresolved",
                                       "error": f"{type(exc).__name__}: {exc}"}
                if rec is None:
                    if auth and not auth.get("text") and auth.get("dead_link"):
                        rec = {"key": key, "status": "dead_link"}
                        for k in ("cite", "title", "url"):
                            if auth.get(k):
                                rec[k] = auth[k]
                    elif not auth or not auth.get("text"):       # Gate B
                        rec = {"key": key, "status": "unresolved"}
                        if auth:
                            for k in ("cite", "title", "url"):
                                if auth.get(k):
                                    rec[k] = auth[k]
                    else:
                        rec = {"key": key, "status": "resolved",
                               "cite": auth.get("cite", key), "title": auth.get("title"),
                               "url": auth.get("url"),
                               "text_verified": auth.get("text_verified"),
                               "text": auth["text"]}
            index[key] = rec
            citations.append(rec)
        return _block(rec)

    return PLACEHOLDER.sub(_repl, draft or ""), citations


def _provider() -> str:
    """Which LLM backend to use: ``anthropic`` or ``openai`` (-compatible)."""
    p = (os.environ.get("HALLUCHECK_PROVIDER") or "").lower()
    if p in ("anthropic", "openai"):
        return p
    if os.environ.get("ANTHROPIC_API_KEY") and not os.environ.get("OPENAI_API_KEY"):
        return "anthropic"
    return "openai"


def _default_model() -> str:
    if _provider() == "anthropic":
        return (os.environ.get("HALLUCHECK_MODEL") or os.environ.get("ANTHROPIC_MODEL")
                or "claude-3-5-sonnet-latest")
    return (os.environ.get("HALLUCHECK_MODEL") or os.environ.get("INSPECTOR_MODEL")
            or os.environ.get("OPENAI_MODEL", "gpt-4o"))


def _client():
    """Construct the inspector client for the active provider. ``$HALLUCHECK_*``
    overrides ``$ANTHROPIC_*`` / ``$OPENAI_*``."""
    if _provider() == "anthropic":
        from anthropic import Anthropic
        kwargs = {}
        key = os.environ.get("HALLUCHECK_API_KEY") or os.environ.get("ANTHROPIC_API_KEY")
        if key:
            kwargs["api_key"] = key
        base = os.environ.get("HALLUCHECK_BASE_URL") or os.environ.get("ANTHROPIC_BASE_URL")
        if base:
            kwargs["base_url"] = base
        return Anthropic(**kwargs)
    from openai import OpenAI
    base = (os.environ.get("HALLUCHECK_BASE_URL") or os.environ.get("INSPECTOR_BASE_URL")
            or os.environ.get("OPENAI_BASE_URL", "http://127.0.0.1:8088/v1"))
    key = (os.environ.get("HALLUCHECK_API_KEY") or os.environ.get("INSPECTOR_API_KEY")
           or os.environ.get("OPENAI_API_KEY", "x"))
    return OpenAI(base_url=base, api_key=key)


def _call_model(client, model: str, prompt: str) -> str:
    """Provider-agnostic single completion -> raw message text. Routes by client
    shape: Anthropic (``client.messages.create``) or OpenAI-compatible
    (``client.chat.completions.create``)."""
    if hasattr(client, "messages") and hasattr(client.messages, "create"):
        r = client.messages.create(
            model=model, max_tokens=1500, temperature=0, system=INSPECT_SYSTEM,
            messages=[{"role": "user", "content": prompt}])
        parts = [getattr(b, "text", "") for b in (getattr(r, "content", None) or [])]
        return "".join(p for p in parts if p)
    r = client.chat.completions.create(
        model=model, temperature=0, max_tokens=1500, timeout=120,
        messages=[{"role": "system", "content": INSPECT_SYSTEM},
                  {"role": "user", "content": prompt}])
    ch = r.choices[0].message
    return ch.content or getattr(ch, "reasoning_content", "") or ""


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip().lower()


def _validate_verdicts(raw: list, auth_by_cite: dict) -> list[dict]:
    out = []
    for v in raw:
        if not isinstance(v, dict):
            continue
        cite, verdict = v.get("cite"), v.get("supports_conclusion")
        if verdict not in _VERDICTS:
            verdict = "unclear"
        quote = v.get("quote") or ""
        auth = auth_by_cite.get(cite)
        grounded = True
        if quote and auth is not None and _norm(quote) not in _norm(auth.get("text", "")):
            grounded = False
            if verdict == "pass":
                verdict = "unclear"          # fabricated supporting quote
        # A "pass" must rest on a real, non-trivial quote: no quote (or a too-short
        # one) is not enough to claim support -> downgrade to unclear.
        if verdict == "pass" and len(_norm(quote)) < MIN_QUOTE_CHARS:
            verdict = "unclear"
        out.append({"cite": cite, "supports_conclusion": verdict, "quote": quote,
                    "quote_grounded": grounded, "rationale": v.get("rationale"),
                    "resolved": auth is not None})
    return out


def _add_unreviewed(verdicts: list[dict], resolved: list[dict]) -> None:
    """A resolved citation the inspector silently skipped must not pass as clean:
    record it as unreviewed/unclear so it still counts as needs-review."""
    seen = {v.get("cite") for v in verdicts}
    for c in resolved:
        cite = c.get("cite", c["key"])
        if cite not in seen and c["key"] not in seen:
            verdicts.append({"cite": cite, "supports_conclusion": "unclear", "quote": "",
                             "quote_grounded": False, "resolved": True, "unreviewed": True,
                             "rationale": "inspector returned no verdict for this citation"})


def _summary(result: dict) -> dict:
    counts = {"pass": 0, "fail": 0, "unclear": 0}
    for v in result.get("verdicts", []):
        counts[v["supports_conclusion"]] = counts.get(v["supports_conclusion"], 0) + 1
    for k in ("unresolved", "dead_links", "invented"):
        counts[k] = len(result.get(k, []))
    return counts


def inspect(draft: str, vocabulary, resolver: Callable[[str], dict | None], *,
            model: str | None = None, client=None, retries: int = 4) -> dict:
    """Substitute citations, then score each with the inspector LLM. Returns
    ``{ok, substituted, citations, verdicts, invented, unresolved, dead_links,
    summary}``. Deterministic findings populate even with no LLM; ``ok`` is False
    only when the LLM call could not be completed."""
    substituted, citations = substitute(draft, vocabulary, resolver)
    resolved = [c for c in citations if c["status"] == "resolved"]
    result = {
        "ok": True, "substituted": substituted, "citations": citations,
        "invented": [c["key"] for c in citations if c["status"] == "invented"],
        "unresolved": [c["key"] for c in citations if c["status"] == "unresolved"],
        "dead_links": [c["key"] for c in citations if c["status"] == "dead_link"],
        "verdicts": [],
    }
    if not resolved:
        result["note"] = "no resolved citations to inspect"
        result["summary"] = _summary(result)
        return result

    auth_by_cite: dict[str, dict] = {}
    for c in resolved:
        auth_by_cite[c.get("cite", c["key"])] = c
        auth_by_cite[c["key"]] = c

    model = model or _default_model()
    if client is None:
        try:
            client = _client()
        except Exception as e:                 # fail soft: keep deterministic findings
            result["ok"] = False
            result["error"] = f"inspector client unavailable: {type(e).__name__}: {e}"
            result["summary"] = _summary(result)
            return result

    prompt = ("DRAFT (each citation replaced with the verbatim source text):\n\n"
              f"{substituted}\n\nJSON:")
    last_exc = None
    for _ in range(retries):
        try:
            msg = _call_model(client, model, prompt)
            raw = _extract_json(msg).get("verdicts")
            if isinstance(raw, list) and raw:
                verdicts = _validate_verdicts(raw, auth_by_cite)
                _add_unreviewed(verdicts, resolved)
                result["verdicts"] = verdicts
                result["summary"] = _summary(result)
                return result
        except Exception as e:
            last_exc = f"{type(e).__name__}: {e}"
    result["ok"] = False
    result["error"] = "no valid verdicts after retries" + (
        f" (last error: {last_exc})" if last_exc else "")
    result["summary"] = _summary(result)
    return result


def aggregate_verdicts(runs: list[list[dict]]) -> list[dict]:
    """Conservatively combine per-citation verdicts across inspector runs:
    **any** ``fail`` -> fail; **unanimous** ``pass`` -> pass; otherwise ``unclear``.
    Carries ``agreement`` (votes for the final verdict), ``samples``, and the raw
    ``votes``. Picks a representative quote that matches the final verdict and is
    grounded when possible."""
    by_cite: dict = {}
    order: list = []
    for run in runs:
        for v in run or []:
            c = v.get("cite")
            if c not in by_cite:
                by_cite[c] = []
                order.append(c)
            by_cite[c].append(v)
    out = []
    for cite in order:
        vs = by_cite[cite]
        votes = [v.get("supports_conclusion") for v in vs]
        if "fail" in votes:
            final = "fail"
        elif votes and all(x == "pass" for x in votes):
            final = "pass"
        else:
            final = "unclear"
        rep = next((v for v in vs if v.get("supports_conclusion") == final
                    and v.get("quote_grounded")), None) \
            or next((v for v in vs if v.get("supports_conclusion") == final), vs[0])
        out.append({**rep, "supports_conclusion": final,
                    "agreement": votes.count(final), "samples": len(vs), "votes": votes})
    return out


def inspect_consensus(draft: str, vocabulary, resolver: Callable[[str], dict | None],
                      *, samples: int = 3, **kw) -> dict:
    """Run :func:`inspect` ``samples`` times and combine the verdicts with
    :func:`aggregate_verdicts` (fail-biased consensus). Reduces the impact of a
    single flaky/colluding judgment. Returns the same shape as ``inspect`` plus a
    ``consensus`` block; if no run completes, returns the first (failed) run."""
    samples = max(1, samples)
    runs = [inspect(draft, vocabulary, resolver, **kw) for _ in range(samples)]
    ok_runs = [r for r in runs if r.get("ok")]
    base = dict(ok_runs[0] if ok_runs else runs[0])
    if not ok_runs:
        return base
    base["verdicts"] = aggregate_verdicts([r.get("verdicts", []) for r in ok_runs])
    base["consensus"] = {"samples": samples, "ok_runs": len(ok_runs)}
    base["summary"] = _summary(base)
    return base
