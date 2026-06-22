"""Brief annotation (combined research memo) + opinion-PDF embedding."""
import pytest

from adapters.maine.adapter import MaineProbateAdapter
from hallucheck import brief, research

DRAFT = ("The petition is time-barred under 18-C §3-108, and In re Estate of "
         "Kruzynski confirms the three-year limit.")


def _packet():
    return research.build_packet(MaineProbateAdapter(),
                                 draft=DRAFT, cites=["18-C §3-108"], fetch_text=False)


def test_memo_markdown_links_citations_into_appendix():
    md = brief.memo_markdown(MaineProbateAdapter(), DRAFT, _packet())
    assert "## Brief" in md
    # the in-text statute cite is now a link to its appendix anchor
    assert "[18-C §3-108](#auth-18-c-3-108)" in md
    # the appendix anchor target exists
    assert 'id="auth-18-c-3-108"' in md
    assert "NOT LEGAL ADVICE" in md


def test_memo_html_links_and_anchor():
    htmls = brief.memo_html(MaineProbateAdapter(), DRAFT, _packet())
    assert htmls.startswith("<!doctype html>")
    assert 'class="brief"' in htmls
    assert 'href="#auth-2000-me-17"' in htmls          # case name -> 2000 ME 17 entry
    assert 'id="auth-2000-me-17"' in htmls


def test_annotate_spans_only_packet_cites():
    pkt = research.build_packet(MaineProbateAdapter(), cites=["18-C §3-108"],
                                fetch_text=False)
    from hallucheck.textnorm import clean
    spans = brief.annotate_spans(MaineProbateAdapter(), clean(DRAFT), pkt)
    # Kruzynski isn't in this packet (only the statute) -> not linked
    assert all(s["anchor"] == "auth-18-c-3-108" for s in spans)


def test_render_pdf_without_path_errors():
    with pytest.raises(ValueError):
        brief.render(MaineProbateAdapter(), DRAFT, _packet(), "pdf")


def test_render_unknown_format():
    with pytest.raises(ValueError):
        brief.render(MaineProbateAdapter(), DRAFT, _packet(), "rtf", path="/tmp/x.rtf")


def test_memo_docx_has_brief_bookmarks_and_links(tmp_path):
    pytest.importorskip("docx")
    out = tmp_path / "memo.docx"
    brief.memo_docx(MaineProbateAdapter(), DRAFT, _packet(), str(out))
    import zipfile
    with zipfile.ZipFile(out) as z:
        xml = z.read("word/document.xml").decode("utf-8")
    assert "bookmarkStart" in xml                      # appendix anchors
    assert "w:anchor" in xml                            # brief -> appendix internal links
    from docx import Document
    texts = "\n".join(p.text for p in Document(str(out)).paragraphs)
    assert "Brief" in texts and "18-C §3-108" in texts


def test_memo_pdf_is_valid_with_internal_links(tmp_path):
    pytest.importorskip("reportlab")
    out = tmp_path / "memo.pdf"
    brief.memo_pdf(MaineProbateAdapter(), DRAFT, _packet(), str(out))
    data = out.read_bytes()
    assert data.startswith(b"%PDF")
    assert b"/Outlines" in data


# --- opinion-PDF embedding (pdfrw) ----------------------------------------- #
def _make_pdf(path, text):
    rl = pytest.importorskip("reportlab.pdfgen.canvas")
    c = rl.Canvas(str(path))
    c.drawString(72, 720, text)
    c.showPage()
    c.save()


def test_append_pdfs_embeds_with_bookmarks(tmp_path):
    pytest.importorskip("pdfrw")
    from hallucheck import pdfmerge
    base = tmp_path / "appendix.pdf"
    op1 = tmp_path / "op1.pdf"
    op2 = tmp_path / "op2.pdf"
    for p, t in ((base, "APPENDIX"), (op1, "OPINION ONE"), (op2, "OPINION TWO")):
        _make_pdf(p, t)
    out = tmp_path / "merged.pdf"
    info = pdfmerge.append_pdfs(str(base), [("Op 1", str(op1)), ("Op 2", str(op2))], str(out))
    assert info["embedded"] == 2 and info["pages"] == 3
    data = out.read_bytes()
    assert data.startswith(b"%PDF")
    assert b"/Outlines" in data


def test_append_pdfs_skips_non_pdf(tmp_path):
    pytest.importorskip("pdfrw")
    from hallucheck import pdfmerge
    base = tmp_path / "appendix.pdf"
    _make_pdf(base, "APPENDIX")
    bad = tmp_path / "notes.txt"
    bad.write_text("not a pdf", encoding="utf-8")
    out = tmp_path / "m.pdf"
    info = pdfmerge.append_pdfs(str(base), [("bad", str(bad))], str(out))
    assert info["embedded"] == 0 and info["skipped"] == 1


def test_opinion_attachments_filters_pdfs():
    pkt = research.build_packet(MaineProbateAdapter(), cites=["2000 ME 17"], fetch_text=False)
    pkt["entries"][0]["sources"]["links"] += [
        {"provider": "local_opinion_file", "url": "/tmp/x.pdf"},
        {"provider": "local_opinion_file", "url": "/tmp/x.txt"},
    ]
    atts = research.opinion_attachments(pkt)
    assert len(atts) == 1 and atts[0][1] == "/tmp/x.pdf"
