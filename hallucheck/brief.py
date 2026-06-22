"""Annotate a brief *in place* and assemble the research memo.

A verification packet (``hallucheck.research``) lists the authorities; this links
them back into the brief. :func:`memo_markdown` / :func:`memo_html` render the
brief with **each citation hyperlinked to its authority** in the appendix, then
the appendix itself — one document an attorney clicks through: citation in the
brief -> the section showing that authority's source text, recorded treatment, and
opinion links.

Citations are located with the adapter's deterministic scanner over the
*normalized* text (so the offsets line up with what the scanner saw); only cites
that made it into the packet are linked. Not legal advice.
"""
from __future__ import annotations

import html

from . import embed
from .textnorm import clean


def annotate_spans(adapter, text: str, packet: dict, *, scope=None) -> list[dict]:
    """Non-overlapping ``{span, anchor}`` for each citation in ``text`` that has a
    packet entry. ``text`` must already be ``textnorm.clean``-ed."""
    by_cite = {e["cite"]: e for e in packet.get("entries", [])}
    spans = []
    for h in adapter.citation_spans(text, scope=scope):
        e = by_cite.get(h["cite"])
        if e:
            spans.append({"span": h["span"], "anchor": e["anchor"]})
    spans.sort(key=lambda s: s["span"][0])
    return spans


def _annotate_md(text: str, spans: list[dict]) -> str:
    out, i = [], 0
    for s in spans:
        a, b = s["span"]
        if a < i:                                    # skip overlaps
            continue
        out.append(text[i:a])
        out.append(f"[{text[a:b]}](#{s['anchor']})")
        i = b
    out.append(text[i:])
    return "## Brief\n\n" + "".join(out)


def _annotate_html(text: str, spans: list[dict]) -> str:
    out, i = [], 0
    for s in spans:
        a, b = s["span"]
        if a < i:
            continue
        out.append(html.escape(text[i:a]))
        out.append(f'<a href="#{html.escape(s["anchor"])}">{html.escape(text[a:b])}</a>')
        i = b
    out.append(html.escape(text[i:]))
    body = "".join(out).replace("\n\n", "</p><p>").replace("\n", "<br>")
    return f'<section class="brief"><h2>Brief</h2><p>{body}</p></section>'


def memo_markdown(adapter, draft: str, packet: dict, *, scope=None) -> str:
    text = clean(draft or "")
    spans = annotate_spans(adapter, text, packet, scope=scope)
    return embed.to_markdown(packet, prologue=_annotate_md(text, spans))


def memo_html(adapter, draft: str, packet: dict, *, scope=None) -> str:
    text = clean(draft or "")
    spans = annotate_spans(adapter, text, packet, scope=scope)
    return embed.to_html(packet, prologue=_annotate_html(text, spans))


def render(adapter, draft: str, packet: dict, fmt: str, *, scope=None,
           path: str | None = None) -> str:
    """Render the combined memo (annotated brief + appendix) as ``md`` or ``html``."""
    fmt = fmt.lower()
    if fmt in ("md", "markdown"):
        out = memo_markdown(adapter, draft, packet, scope=scope)
    elif fmt == "html":
        out = memo_html(adapter, draft, packet, scope=scope)
    else:
        raise ValueError(f"memo supports md/html, not {fmt!r}")
    if path:
        import pathlib
        pathlib.Path(path).write_text(out, encoding="utf-8")
    return out
