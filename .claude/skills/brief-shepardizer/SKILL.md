---
name: brief-shepardizer
description: >
  Build an attorney-reviewable citation-verification packet ("authorities
  appendix") from a legal brief or memo. Extracts every citation, retrieves the
  real source text as proof, attaches read/verify links across free, subscription,
  and bar-membership research services, cross-links related authorities, and
  renders a Markdown/HTML/DOCX/PDF appendix with internal bookmarks so each
  citation jumps to the section showing its source text and any recorded treatment.
  Use when asked to verify, link, Shepardize, or assemble authorities for a brief
  or research memo. NOT a substitute for attorney review — it cannot determine
  negative treatment / whether a case is still good law.
---

# Brief Shepardizer

Turn a draft brief or memo into a **verification packet**: for every citation,
the real authority text (proof it exists and reads as cited), a SHA-256 of that
text, links to read and independently verify it, cross-links to related
authorities, and a slot for the attorney's treatment findings. Built on
`hallucheck` (`hallucheck.research` + `hallucheck.embed`).

## When to use

- "Verify / link / check the citations in this brief."
- "Build an authorities appendix / research memo for these cases and statutes."
- "Help me Shepardize this" (assemble the materials to review by hand).

## Hard rule — say this every time

This tool **organizes citations for human review; it does not validate them.** It
cannot tell you whether a case is still good law or has negative treatment. Every
output must be reviewed by a **licensed attorney** who reads each source in full.
Never present the packet as verification. The disclaimer is stamped on every
rendered document — keep it there.

## Workflow

1. **Pick the adapter + scope.** The adapter supplies the closed corpus (which
   citations are recognized and resolvable). The reference adapter is `maine`
   (Maine Uniform Probate Code); a host repo may register its own. Scope narrows
   the vocabulary to a form/topic (e.g. `--scope DE-101`).

2. **See what's cited (deterministic, offline):**
   ```bash
   hallucheck scan --adapter maine --draft brief.txt
   ```
   `leaked` = citations written in prose (unverified by the protocol);
   `unresolvable` = not in the trusted index — flag these to the attorney first.

3. **Build the packet from the brief:**
   ```bash
   # offline (bundled text); drop --no-fetch to fetch live statute text
   hallucheck pack --adapter maine --draft brief.txt --no-fetch \
       --format pdf --out authorities.pdf
   ```
   Add `--cite "2000 ME 17"` (repeatable) to include authorities not found by the
   scanner. Formats: `md`, `html`, `docx`, `pdf`, `json`. DOCX/PDF need the extra:
   `pip install 'llm-hallucination-checker[docs]'`.

   Opt-in network enrichment for cases (free CourtListener API; set
   `COURTLISTENER_TOKEN` to raise rate limits):
   ```bash
   hallucheck cl-lookup --cite "2000 ME 17" --citing 5   # opinion + later citing cases
   hallucheck pack ... --courtlistener               # add live opinion links/excerpts
   hallucheck pack ... --citing 5                     # + cited-by list for treatment review
   hallucheck pack ... --fetch-opinions ./opinions   # download opinion files + link them
   ```
   `--citing N` lists the N most-recent opinions that cite each case — the
   references to review for negative treatment (it lists *who cites it*, never
   whether the treatment is negative). A CourtListener hit is a **lead, not a
   verification** — confirm it is the right case and still good law.

4. **Record the attorney's treatment** (the Shepardize result) in a JSON file and
   pass `--treatments`. An authority listed under `authorities` that is also in the
   packet is auto-linked, so a negative-treatment note links onward to the next
   authority's section:
   ```json
   {
     "2000 ME 17": {
       "status": "caution",
       "note": "Confirm carry-forward from former 18-A to 18-C §3-108.",
       "reviewed_by": "J. Attorney, 2026-06-21",
       "authorities": [{"cite": "18-C §3-108", "label": "successor statute"}]
     }
   }
   ```
   `status` is the attorney's call: `good` / `caution` / `negative` / `unreviewed`.
   ```bash
   hallucheck pack --adapter maine --draft brief.txt --no-fetch \
       --treatments treatments.json --format docx --out authorities.docx
   ```

5. **Hand off for review.** Tell the user exactly what to check: open each
   authority's links, confirm the source text supports the proposition, and run
   the citation through Westlaw/Lexis (subscription) or Fastcase·vLex via their
   Maine/NH/MA bar membership (portal links + the citation to paste are in the
   packet) to check negative treatment. Use the "save snapshot" (Internet Archive)
   link to capture durable proof of the text.

## What the rendered appendix contains, per authority

- citation + title, with a bookmark/anchor;
- **source text** with its SHA-256 (proof);
- read/verify links: official source, Google Scholar, CourtListener (deep link for
  reporter cites), web search, Internet Archive snapshot; plus labeled
  subscription (Westlaw/Lexis) and bar (MSBA/NHBA/MBA Fastcase·vLex) portals;
- **treatment** (attorney findings) with links to cited authorities;
- **related authorities** (cross-linked).

## Don't

- Don't claim a citation is "verified," "valid," or "good law."
- Don't invent citations, URLs, or treatments — only the attorney fills treatment.
- Don't remove or weaken the disclaimer on generated documents.
- Don't rely on `unresolvable` citations; surface them for manual review.
