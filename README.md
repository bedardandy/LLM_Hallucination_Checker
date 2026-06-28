> **AI/legal-use disclosure:** This repository is experimental, AI-assisted workflow software. It is not legal advice, not a primary legal source, and not lawyer-reviewed as a complete statement of law. Outputs are first drafts for human review, intended to reduce creation effort while increasing focused review effort. See [AI_DISCLOSURE.md](AI_DISCLOSURE.md).

# LLM Hallucination Checker

Catch hallucinated citations in LLM output by turning *creative generation* into
*precise retrieval + validation*. Force the model to cite **only** by emitting
closed-vocabulary `[[REF: KEY]]` placeholders, substitute each one with the
**real source text**, then run a cold-eyes inspector that checks, per citation,
whether the conclusion is actually supported — and attach tamper-evident proof
that the check ran.

> Corpus-agnostic core + pluggable adapters. A complete **Maine probate law**
> adapter ships as a reference.

> ⚠️ **EXPERIMENTAL — NOT LEGAL ADVICE.** This is experimental, AI/LLM-assisted
> software. It helps *surface and organize* citations for human review; it does
> **not** verify that an authority is correctly characterized, in force, or still
> good law, and it **cannot determine negative treatment**. Use **extreme
> caution** before relying on it in any production or client-facing system, and
> **never** rely on output that a **licensed attorney** has not independently
> reviewed. See [`DISCLAIMER.md`](DISCLAIMER.md).

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
| **Inspect** placeholdered drafts (pass/fail/unclear + grounded quote; Claude or OpenAI; `--samples` consensus) | `hallucheck.inspector` | LLM |
| **Scan** for cites written outside the protocol, unresolvable cites, fabricated URLs | `hallucheck.scan` | offline |
| **Dead-link** detection (DEAD ≠ BLOCKED: only 404/410/NXDOMAIN fail) | `hallucheck.links` | network |
| **Attest** — signed, hash-chained receipts proving the check ran | `hallucheck.attest` | offline |
| **Link & verify** — source links + a packet that *proves the cited text exists*, rendered to MD/HTML/DOCX/PDF for attorney review | `hallucheck.sources` · `hallucheck.research` · `hallucheck.embed` | offline* |

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

## Inspector & benchmark

The inspector LLM runs on **Claude or any OpenAI-compatible endpoint** — set
`HALLUCHECK_PROVIDER=anthropic` (uses `ANTHROPIC_API_KEY`) or leave it for the
OpenAI path; `HALLUCHECK_MODEL`/`HALLUCHECK_BASE_URL`/`HALLUCHECK_API_KEY`
override either. Because a single judge is non-deterministic, `--samples N` runs it
N times and takes a **fail-biased consensus** (any `fail` → fail; only a unanimous,
grounded `pass` → pass). A `pass` must rest on a real, non-trivial quote that
appears verbatim in the source, or it is downgraded to `unclear`.

The **deterministic** layer (scanner + gates) is measurable, so regressions are
caught in CI:

```bash
hallucheck bench --adapter maine        # precision/recall/F1 over labeled adversarial drafts
hallucheck inspect --adapter maine --scope DE-101 --draft draft.txt --samples 3
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

## Link, verify & Shepardize (for attorney review)

Catching a fabricated cite is half the job; an attorney still has to *read the
authority* and confirm it says what it's cited for and is still good law. The
linking layer assembles that review packet — and, crucially, **embeds proof the
cited text exists**: the real source text, its SHA-256, and durable links.

```bash
# every place to read/verify one citation (free, subscription, bar-membership)
hallucheck sources --adapter maine --cite "457 A.2d 1123"

# resolve a case to its opinion + the later opinions that cite it (treatment review)
hallucheck cl-lookup --cite "457 A.2d 1123" --citing 5

# build an "authorities appendix" from a brief — internal bookmarks let each
# citation jump to the section showing its source text + recorded treatment
pip install -e ".[docs]"        # adds python-docx + reportlab for DOCX/PDF
hallucheck pack --adapter maine --draft brief.txt --no-fetch \
    --format pdf --out authorities.pdf
hallucheck pack --adapter maine --draft brief.txt --treatments treatments.json \
    --citing 5 --format docx --out authorities.docx   # + opinion + cited-by links
hallucheck pack --adapter maine --draft brief.txt \
    --fetch-opinions ./opinions --format pdf --out authorities.pdf  # download files

# annotate the brief IN PLACE: each citation links to its authority in the appendix
hallucheck memo --adapter maine --draft brief.txt --no-fetch --format html --out memo.html

# splice the downloaded opinion PDFs into the appendix as bookmarked pages
hallucheck pack --adapter maine --draft brief.txt --fetch-opinions ./ops \
    --embed-opinions --format pdf --out authorities.pdf

# with a free COURTLISTENER_TOKEN, use the real opinion text as the case excerpt
COURTLISTENER_TOKEN=... hallucheck pack --adapter maine --draft brief.txt \
    --opinion-text 4000 --format pdf --out authorities.pdf
```

Each authority in the packet (MD/HTML/DOCX/PDF) carries: the **source text** with
its hash (proof); **read/verify links** — official source, Google Scholar,
CourtListener (a deep citation link for reporter cites), web search, and an
**Internet Archive "save snapshot"** link to capture timestamped proof; an opt-in
**CourtListener** lookup (`--courtlistener`) that resolves a case to its *real
opinion*, with `--citing N` listing the later opinions that cite it (the cited-by
references an attorney reviews for negative treatment) and `--fetch-opinions`
downloading the file into the appendix — plus
clearly-labeled **subscription** (Westlaw, Lexis) and **bar-membership** portals
(Maine/NH/MA bar → Fastcase·vLex; many Maine attorneys hold all three); the
attorney's **treatment** findings (cross-linked to the next authority, so a
negative-treatment note links onward); and **related authorities**.

**`hallucheck memo`** produces a single document (Markdown, HTML, DOCX, or PDF) —
the brief with each citation hyperlinked to its appendix entry (real internal
links/bookmarks in DOCX/PDF), followed by the appendix — so a reviewer jumps from a
citation in the brief straight to its source text, treatment, and opinion links.
With `--embed-opinions`, downloaded opinion PDFs are spliced
into the appendix PDF as bookmarked pages (appendix + full opinions in one file).

It does **not** decide whether a case is good law — negative treatment can't be
derived from a closed corpus. The attorney records that in `treatments.json`
(`{cite: {status, note, reviewed_by, authorities}}`), which the packet renders as
first-class, cross-linked entries. Subscription/bar entries are never guessed deep
links — just the service's real portal plus the citation to paste. The
[`brief-shepardizer`](.claude/skills/brief-shepardizer/SKILL.md) Claude Code skill
drives this workflow end to end.

## Threat model

What it defends against (homoglyph/zero-width evasion, `§§` list smuggling,
spelled-out and out-of-scope cites, no-protocol prose, dropped/fabricated inspector
quotes) and the **intentional gaps** (non-enumerable URL hosts, streaming proxy,
mischaracterization of a real wrapped cite) are documented in
[`THREATS.md`](THREATS.md), each row tied to a regression test.

## Bundled adapters

| Adapter | Corpus | Vocabulary |
|---|---|---|
| `maine` | Maine Uniform Probate Code (Title 18-C) + Law Court cases, bundled | **closed** — a fixed, offline allow-list (the strongest guarantee) |
| `courtlistener` | **any** jurisdiction's case law, via the free CourtListener API | **open** — a cite resolves if CourtListener returns a match |

```bash
# open-vocabulary: seed the allow-list with the cites you'll use, each confirmed live
hallucheck pack --adapter courtlistener --scope "457 A.2d 1123; 2000 ME 17" \
    --draft brief.txt --citing 5 --format pdf --out authorities.pdf
```

The `courtlistener` adapter trades the closed-vocabulary guarantee for coverage:
the `[[REF:]]` protocol still confines the model to seeded keys, but the universe
of valid cites is no longer a fixed list you control, and existence is confirmed
over the network at resolve-time (not offline). A match is a lead to read, not a
verified citation.

## Write your own adapter

Implement `hallucheck.adapter.Adapter`: `build_vocabulary`, `resolve`,
`citation_spans`, `url_in_index`, `index_urls`, `config_digest`, `disclaimer`.
Register it (`hallucheck.adapter.register("mycorpus", "my.module:MyAdapter")`) or
pass `--adapter my.module:MyAdapter`. See `adapters/maine/` (closed) and
`adapters/courtlistener/` (open) for full examples.

Prove it satisfies the contract with the **conformance kit** — one test, or one
command:

```python
from hallucheck import conformance
def test_conformance():
    conformance.assert_conforms(MyAdapter(), sample_text="…1 A.2d 2…",
                                resolves_cites=["1 A.2d 2"], in_scope="…")
```
```bash
hallucheck conformance --adapter my.module:MyAdapter --draft sample.txt --cite "1 A.2d 2"
```

It checks shapes (vocabulary/`citation_spans`/`resolve`/`url_in_index`/
`index_urls`/`config_digest`), span bounds, determinism, and graceful handling of
unknown keys — reporting every violation instead of crashing.

## Incorporate by reference

Pin it in another repo and supply only your adapter + data locally:

```
llm-hallucination-checker @ git+https://github.com/bedardandy/LLM_Hallucination_Checker@v0.1.0
```

## Development

```bash
pip install -e ".[dev,docs]"     # tests + ruff + mypy + DOCX/PDF renderers
ruff check .                     # lint (style is deliberately terse; see pyproject)
mypy hallucheck                  # type check
pytest --cov=hallucheck          # tests + coverage (CI gates at 78%)
```

Cross-check the bundled Maine case law against CourtListener (existence/metadata,
**not** holdings) with `python tools/verify_caselaw.py` (or `hallucheck.caseaudit`
in code).

CI (`.github/workflows/ci.yml`) runs lint, type-check, and the test matrix on
3.10/3.12. Pushing a `vX.Y.Z` tag triggers `release.yml`, which builds the sdist +
wheel and creates a GitHub Release; PyPI publishing is opt-in (set the repo
variable `PUBLISH_TO_PYPI=true` with trusted publishing configured).

## License

MIT.
