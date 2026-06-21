# Maine probate adapter (reference)

A complete `hallucheck.adapter.Adapter` over the **Maine Uniform Probate Code**
(Title 18-C), its Law Court case law, and non-18-C cross-references.

- **Vocabulary** — Title 18-C sections, cases, and cross-refs; scope to an example
  form (`--scope DE-101`, `--scope AD-008`) or the whole index (no scope).
- **Resolution** — statute text fetched live from legislature.maine.gov (which
  403s non-browser User-Agents, so a browser UA is used); case "text" is the
  summarized holding.
- **Scanner** — recognizes `18-C §3-401`, `18-C M.R.S.A. § 3-401`, bare `§3-203`,
  `36 M.R.S. §4107`, neutral cites `2000 ME 17`, reporter cites `457 A.2d 1123`,
  and case **names** (`In re Estate of Kruzynski` → `2000 ME 17`).
- **URL check** — offline: a `legislature.maine.gov` statute URL whose section
  isn't in the index is fabricated for certain.

## Bundled data

`data/` carries a snapshot of the index (`18c-sections.json`, `caselaw.json`,
`cross-refs.json`) and two example per-form vocabularies (`forms/DE-101.json`,
`forms/AD-008.json`) so the adapter runs standalone. The statute metadata is
public record from legislature.maine.gov; the authority *selection* and holdings
are experimental AI annotations — see the disclaimer.

In a host repo (e.g. `maine-probate-forms`) subclass `MaineProbateAdapter` to read
that repo's full per-form `statutes.json` instead of the bundled examples; the
protocol is identical.

## Verification packets

This adapter feeds the linking layer directly:

```bash
hallucheck sources --adapter maine --cite "2000 ME 17"
hallucheck pack    --adapter maine --draft brief.txt --no-fetch --format pdf --out authorities.pdf
```

`pack` resolves each cite to its bundled/live text (proof), attaches read/verify
links (legislature.maine.gov, Google Scholar, CourtListener, Internet Archive, and
labeled Westlaw/Lexis/Fastcase·vLex portals), and renders a bookmarked authorities
appendix for **attorney review**. It does not determine negative treatment.

**Not legal advice.**
