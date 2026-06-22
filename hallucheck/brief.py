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
import re

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


def _paragraphs(text: str) -> list[str]:
    return [p for p in re.split(r"\n\s*\n", text) if p.strip()]


def _segments(adapter, para: str, packet: dict, scope) -> list[tuple[str, str | None]]:
    """Split one (cleaned) paragraph into ``(text, anchor|None)`` runs, anchoring
    each citation that has a packet entry."""
    spans = annotate_spans(adapter, para, packet, scope=scope)
    segs: list[tuple[str, str | None]] = []
    i = 0
    for s in spans:
        a, b = s["span"]
        if a < i:
            continue
        if para[i:a]:
            segs.append((para[i:a], None))
        segs.append((para[a:b], s["anchor"]))
        i = b
    if para[i:]:
        segs.append((para[i:], None))
    return segs


def memo_docx(adapter, draft: str, packet: dict, path: str, *, scope=None) -> str:
    text = clean(draft or "")

    def prologue(doc, internal_link):
        doc.add_heading("Brief", level=1)
        for para in _paragraphs(text):
            p = doc.add_paragraph()
            for seg, anchor in _segments(adapter, para, packet, scope):
                internal_link(p, anchor, seg) if anchor else p.add_run(seg)

    return embed.to_docx(packet, path, prologue=prologue)


def memo_pdf(adapter, draft: str, packet: dict, path: str, *, scope=None) -> str:
    import xml.sax.saxutils as su
    text = clean(draft or "")
    paras = ["<b>Brief</b>"]
    for para in _paragraphs(text):
        chunk = []
        for seg, anchor in _segments(adapter, para, packet, scope):
            esc = su.escape(seg).replace("\n", "<br/>")
            chunk.append(f'<a href="#{su.escape(anchor)}" color="blue">{esc}</a>'
                         if anchor else esc)
        paras.append("".join(chunk))
    return embed.to_pdf(packet, path, prologue_paras=paras)


def render(adapter, draft: str, packet: dict, fmt: str, *, scope=None,
           path: str | None = None) -> str:
    """Render the combined memo (annotated brief + appendix): ``md``/``html`` return
    the string (written to ``path`` when given); ``docx``/``pdf`` require ``path``."""
    fmt = fmt.lower()
    if fmt in ("md", "markdown"):
        out = memo_markdown(adapter, draft, packet, scope=scope)
    elif fmt == "html":
        out = memo_html(adapter, draft, packet, scope=scope)
    elif fmt == "docx":
        if not path:
            raise ValueError("docx output requires a path")
        return memo_docx(adapter, draft, packet, path, scope=scope)
    elif fmt == "pdf":
        if not path:
            raise ValueError("pdf output requires a path")
        return memo_pdf(adapter, draft, packet, path, scope=scope)
    else:
        raise ValueError(f"memo supports md/html/docx/pdf, not {fmt!r}")
    if path:
        import pathlib
        pathlib.Path(path).write_text(out, encoding="utf-8")
    return out
