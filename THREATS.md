# Threat model & known limitations

What this tool defends against, how, and — honestly — what it does **not** catch.
The primary guarantee is the **closed-vocabulary placeholder protocol**; the
deterministic scanner is a *safety net* for output that ignores the protocol, not
a citation parser.

## Defended (with regression tests)

| Attack / failure | Defense | Test |
|---|---|---|
| Invent a citation key | Gate A: key ∉ vocabulary → `invented` (no LLM) | `test_inspector`, `test_adversarial` |
| Cite a key whose source can't be fetched | Gate B: → `unresolved` | `test_inspector` |
| Author URL is a 404 | resolved as `dead_link` (≠ `unresolved`) | `test_maine_adapter` |
| Skip the protocol, mischaracterize a **real** statute in prose | strict `leaked`: *any* unwrapped cite blocks (`require_protocol`) | `test_adversarial::test_no_protocol_prose_is_blocked` |
| Smuggle a cite outside `[[REF:]]` while using it elsewhere | strict `leaked` | `test_adversarial::test_mixed_buckets_in_one_draft` |
| Wrap a **real but out-of-scope** cite in a placeholder | offline `out_of_vocab` blocks (parity with Gate A) | `test_adversarial::test_out_of_scope_cite_wrapped_in_placeholder_blocks` |
| Spelled-out reverse order `§9-999 of Title 18-C` | reverse pattern | `test_adversarial::test_spelled_out_reverse_order` |
| Hide a digit with a non-breaking/en-dash hyphen | `textnorm.clean` folds hyphen homoglyphs | `test_adversarial::test_homoglyph_and_zero_width_evasion` |
| Split a section number with a zero-width space / BOM | `textnorm.clean` strips invisibles | same |
| Bury a fabricated item in a `§§ a, b, c` list | enumerated-list scanner | `test_adversarial::test_plural_section_list_catches_every_item` |
| Fabricated/placeholder URL (`example.com`, bad 18-C section URL) | URL classifier | `test_scan`, `test_adversarial::test_url_classes` |
| Inspector LLM silently drops a verdict for a resolved cite | reconcile → `unreviewed/unclear` | `test_adversarial::test_inspector_flags_dropped_verdict` |
| Inspector "supports" with a quote not in the source | quote-grounding downgrade to `unclear` | `test_inspector::test_inspect_downgrades_fabricated_quote` |
| Operator claims "it passed" without running it | HMAC-signed, hash-chained receipts (operator key) | `test_attest` |
| Subsection false-positive `§3-401(a)` flagged as invented | subsection-tolerant resolution | `test_adversarial::test_subsection_key_is_not_a_false_positive` |

All four integration surfaces (CLI, Claude Code Stop hook, OpenAI-compatible
proxy, guard API) route through the same `guard.evaluate` core, tested end-to-end
in `test_integration.py` (the proxy test runs a real HTTP round-trip).

## Not caught (by design / known gaps)

1. **Fabricated URL on a non-enumerable host.** A made-up `law.justia.com` or
   `courts.maine.gov` URL is `unknown`, not `fabricated` — only
   `legislature.maine.gov` section URLs are *structurally* checkable offline.
   Justia has millions of valid pages absent from our index; calling those
   "fabricated" would be false positives. **Mitigation:** `check_live=True`
   probes `unknown`/`fabricated` URLs (a 404 → `dead_urls`).
2. **Streaming proxy responses.** The reference proxy forwards `stream:true`
   **unverified** (`test_proxy_streaming_is_passthrough_documented_gap`).
   **Mitigation:** buffer-and-inspect in production, or rely on the Stop hook.
3. **Mischaracterization of a real, in-scope, properly-wrapped citation.** This is
   exactly what the **inspector LLM** judges; the deterministic layer cannot. The
   inspector is non-deterministic — we make faking harder (forced verbatim quote
   that must appear in the source; dropped verdicts → unreviewed) but a weak or
   colluding inspector can still mis-judge. **Defense-in-depth:** fail-closed gate
   + attestation so the judgment is at least recorded and reproducible.
4. **Exotic citation surface forms.** Non-adjacent references ("Title 18-C governs;
   under Section 9-999 …" with words in between) are intentionally *not* linked to
   avoid false positives on generic "Section N". The protocol — not the scanner —
   is the guarantee.
5. **Index freshness.** Resolution is only as current as the bundled/host index; a
   section added upstream after the snapshot reads as `unresolvable` until the
   index is refreshed (see `tools/check_upstream.py` in the host repo).

## Posture

Deterministic findings (gates, scanner, URLs, dead links) are **fail-closed and
LLM-free** — safe in a blocking hook. The inspector LLM is **opt-in** and additive.
A receipt proves the check *ran and what it found*; only a fail-closed gate proves
the agent *heeded* a failure.
