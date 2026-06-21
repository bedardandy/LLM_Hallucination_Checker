# LLM Hallucination Checker

Catch hallucinated citations in LLM output by turning *creative generation* into
*precise retrieval + validation*. Force the model to cite **only** by emitting
closed-vocabulary `[[REF: KEY]]` placeholders, substitute each one with the
**real source text**, then run a cold-eyes inspector that checks, per citation,
whether the conclusion is actually supported — and attach tamper-evident proof
that the check ran.

> Corpus-agnostic core + pluggable adapters. A complete **Maine probate law**
> adapter ships as a reference. Not legal advice.

## Why this works

- **Eliminates the "telephone game."** The model never reprints source text from
  memory, so it can't drift on the wording of a statute or case.
- **Closed vocabulary, not free text.** Two deterministic gates make an invented
  citation impossible to pass silently: a key not in the allow-list is `invented`
  (no model in the loop); an in-vocab key whose text can't be fetched is
  `unresolved`; a dead authority URL is `dead_link`.
- **Separates drafting from fact-checking.** A zero-temperature inspector compares
  each conclusion to the literal source and must **quote the exact span** it
  relied on — a fabricated supporting quote is downgraded automatically.

## Four capabilities

| Capability | Module | Network/LLM |
|---|---|---|
| **Inspect** placeholdered drafts (pass/fail/unclear + grounded quote) | `hallucheck.inspector` | LLM |
| **Scan** for cites written outside the protocol, unresolvable cites, fabricated URLs | `hallucheck.scan` | offline |
| **Dead-link** detection (DEAD ≠ BLOCKED: only 404/410/NXDOMAIN fail) | `hallucheck.links` | network |
| **Attest** — signed, hash-chained receipts proving the check ran | `hallucheck.attest` | offline |

## Quickstart (Maine adapter)

```bash
pip install -e ".[llm]"        # core is stdlib-only; [llm] adds openai for the inspector

# the closed vocabulary a model may cite from, for one form
hallucheck emit-prompt --adapter maine --scope DE-101

# deterministic scan (offline): catches leaked/unresolvable cites + fabricated URLs
echo "The court must rule for us, see 18-C §9-999 and https://example.com/x" \
  | hallucheck scan --adapter maine

# full inspection with attestation
export ATTEST_HMAC_KEY=operator-only-secret
hallucheck inspect --adapter maine --scope DE-101 --draft draft.txt --attest --log run.jsonl
hallucheck verify-log run.jsonl
```

## Inject into a harness

One shared guard core (`hallucheck.guard.evaluate`) powers both:

- **Claude Code** — a blocking Stop hook:
  ```json
  {"hooks": {"Stop": [{"hooks": [{"type": "command",
     "command": "python3 -m hallucheck.hooks.claude_code --adapter maine"}]}]}}
  ```
- **Codex / Hermes / LiteLLM / anything OpenAI-compatible** — a guard proxy:
  ```bash
  UPSTREAM_BASE_URL=https://api.example/v1 PROXY_FAIL_CLOSED=1 \
      python3 -m hallucheck.proxy --adapter maine --port 8099
  ```

## Proving it was on

A receipt (`{input_sha256, findings, verdict_digest, config_digest, needs_review,
nonce}`) is HMAC-signed with an **operator-held** key the agent can't forge, and
chained into an append-only log (each entry pins the prior line's hash).
`verify --input` binds a receipt to the exact text; `verify-log` catches
tampering or reordering. A receipt proves the guard *ran and what it found*; only
the **fail-closed** hook/proxy proves the agent *heeded* a failure.

## Threat model

What it defends against (homoglyph/zero-width evasion, `§§` list smuggling,
spelled-out and out-of-scope cites, no-protocol prose, dropped/fabricated inspector
quotes) and the **intentional gaps** (non-enumerable URL hosts, streaming proxy,
mischaracterization of a real wrapped cite) are documented in
[`THREATS.md`](THREATS.md), each row tied to a regression test.

## Write your own adapter

Implement `hallucheck.adapter.Adapter`: `build_vocabulary`, `resolve`,
`citation_spans`, `url_in_index`, `index_urls`, `config_digest`, `disclaimer`.
Register it (`hallucheck.adapter.register("mycorpus", "my.module:MyAdapter")`) or
pass `--adapter my.module:MyAdapter`. See `adapters/maine/` for a full example.

## Incorporate by reference

Pin it in another repo and supply only your adapter + data locally:

```
llm-hallucination-checker @ git+https://github.com/bedardandy/LLM_Hallucination_Checker@v0.1.0
```

## License

MIT.
