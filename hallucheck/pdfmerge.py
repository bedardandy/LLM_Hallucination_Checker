"""Splice downloaded opinion PDFs into the authorities appendix as bookmarked
pages (pure-Python ``pdfrw``; part of the ``[docs]`` extra).

After ``pack --fetch-opinions`` downloads the available opinion files, this
appends each PDF after the generated appendix and adds a top-level PDF outline
(sidebar bookmark) jumping to the first page of each embedded opinion — so an
attorney gets the appendix *and* the full opinions in one bookmarked file. Only
PDF attachments are embedded (text/HTML opinions are linked, not spliced).
"""
from __future__ import annotations


def append_pdfs(base_pdf: str, attachments, out_path: str) -> dict:
    """Append ``attachments`` (``[(title, pdf_path)]``) to ``base_pdf``, writing
    ``out_path`` with an outline entry per embedded opinion. Unreadable/empty PDFs
    are skipped. Returns ``{embedded, skipped, pages}``."""
    try:
        from pdfrw import IndirectPdfDict, PdfName, PdfReader, PdfString, PdfWriter
    except Exception as e:                                # pragma: no cover
        raise RuntimeError("PDF embedding needs the [docs] extra: pip install "
                           "'llm-hallucination-checker[docs]'") from e

    writer = PdfWriter()
    base = PdfReader(base_pdf)
    writer.addpages(base.pages)
    pages = len(base.pages)

    nodes, skipped = [], 0
    outlines = IndirectPdfDict(Type=PdfName.Outlines)
    for title, path in attachments:
        try:
            r = PdfReader(path)
            first = r.pages[0]
        except Exception:                                # not a readable PDF
            skipped += 1
            continue
        writer.addpages(r.pages)
        pages += len(r.pages)
        nodes.append(IndirectPdfDict(Title=PdfString.encode(str(title)),
                                     Parent=outlines, Dest=[first, PdfName.Fit]))

    if nodes:
        for i, n in enumerate(nodes):
            if i:
                n.Prev = nodes[i - 1]
            if i < len(nodes) - 1:
                n.Next = nodes[i + 1]
        outlines.First, outlines.Last, outlines.Count = nodes[0], nodes[-1], len(nodes)
        writer.trailer.Root.Outlines = outlines

    writer.write(out_path)
    return {"embedded": len(nodes), "skipped": skipped, "pages": pages}
