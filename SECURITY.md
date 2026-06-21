# Security

This is experimental software (see [`DISCLAIMER.md`](DISCLAIMER.md)). It is a
**defensive** tool — its job is to make AI citation output checkable — but it does
perform network I/O and write files, so it has an attack surface worth stating
plainly.

## Reporting a vulnerability

Please open a GitHub security advisory (Security → "Report a vulnerability") or a
private channel to the maintainer rather than a public issue for anything
exploitable. Include a reproduction and the affected version.

## Trust model & hardening

- **Network is opt-in.** The deterministic core (scanner, gates, attestation) and
  offline packet building never touch the network. Live calls happen only when you
  pass `--check`, `--courtlistener`/`--citing`, `--fetch-opinions`, or run the
  inspector/proxy.
- **SSRF guard on downloads.** `hallucheck.courtlistener.fetch_file` (used by
  `research.attach_opinions` and `pack --fetch-opinions`) only fetches `http(s)`
  URLs whose host resolves to a **publicly-routable** address. It rejects
  `file://` / `ftp://` / `data:` and any URL resolving to a private, loopback,
  link-local (incl. the cloud-metadata `169.254.169.254`), reserved, or multicast
  address. *Residual risk:* DNS rebinding between the check and the connect — an
  accepted limitation for an opt-in research download.
- **Size caps.** API responses (`MAX_JSON_BYTES`) and downloaded opinion files
  (`MAX_FILE_BYTES`, also a per-call `max_bytes`) are capped; a partial file that
  exceeds the cap is deleted.
- **Path safety.** Downloaded files are named from the sanitized citation anchor
  (alphanumerics/hyphens) with an allow-listed extension, so an API-supplied URL
  cannot direct a write outside the chosen directory.
- **Output escaping.** Rendered HTML/PDF/DOCX escape all dynamic text (source
  text, case names, snippets); HTML external links use `rel="noopener"`. Markdown
  output is plain text intended for human/preview use.
- **Untrusted inputs.** Treat drafts, adapter corpus data, and third-party API
  responses (CourtListener, statute sites) as untrusted content: this tool is
  meant to *surface* citations for review, never to auto-act on them. The
  attestation HMAC key (`ATTEST_HMAC_KEY`) and any `COURTLISTENER_TOKEN` are
  operator-held secrets — keep them out of logs and commits.

## Known gaps

See [`THREATS.md`](THREATS.md) for the citation-detection threat model and its
documented limitations (streaming proxy passthrough, non-enumerable URL hosts,
inspector non-determinism, no negative-treatment determination).
