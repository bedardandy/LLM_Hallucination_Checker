# Disclaimer

**EXPERIMENTAL SOFTWARE — NOT LEGAL ADVICE.**

This project is experimental and AI/LLM-assisted. It is a tool for **surfacing and
organizing citations for human review** — it does **not** verify that any authority
is correctly characterized, currently in force, or still good law, and it **cannot
determine negative treatment** (whether a case has been overruled, reversed,
limited, or criticized).

Treat every result as **unverified** until a **licensed attorney** has:

1. read each cited source **in full**,
2. confirmed it **says what it is cited for**, and
3. checked its **subsequent history / treatment** (e.g., via Westlaw, Lexis, or
   Fastcase·vLex through bar membership).

AI/LLM-generated content — including the selection of authorities, holding
summaries, and any analysis — **can be wrong, out of date, or fabricated.**

## Production use

Use **extreme caution** before relying on this software in any production,
automated, or client-facing system. Outputs must not be filed, served, or relied
upon without independent review by a licensed attorney. Nothing here creates an
attorney–client relationship.

## Corpus data

The bundled Maine adapter's statute titles/text are drawn from public records
(legislature.maine.gov), but the **selection** of authorities and all **holding
summaries** are model annotations and may be incorrect. Verify against the current
statute and the actual opinions.

## How this is enforced in code

Every generated artifact (verification packets and the Markdown/HTML/DOCX/PDF
appendices produced by `hallucheck.embed`) is stamped with this disclaimer plus
the active corpus adapter's own disclaimer. The text lives in
`hallucheck/disclaimer.py` (`LIBRARY_DISCLAIMER`, `SHORT_DISCLAIMER`,
`REVIEW_REMINDER`, `combined()`); do not remove or weaken it.

By using this software you acknowledge the above.
