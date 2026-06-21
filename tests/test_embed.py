"""Rendering a packet to Markdown / HTML (core) and DOCX / PDF (optional extra)."""
import zipfile

import pytest

from adapters.maine.adapter import MaineProbateAdapter
from hallucheck import embed, research


def _packet():
    treatments = {"2000 ME 17": {"status": "caution", "note": "verify currency",
                                 "authorities": [{"cite": "18-C §3-108",
                                                  "label": "successor statute"}]}}
    return research.build_packet(
        MaineProbateAdapter(), cites=["2000 ME 17", "18-C §3-108"],
        fetch_text=False, treatments=treatments)


def test_markdown_has_disclaimer_anchors_links_and_proof():
    md = embed.to_markdown(_packet())
    assert "NOT LEGAL ADVICE" in md
    assert 'id="auth-2000-me-17"' in md           # section anchor
    assert "(#auth-2000-me-17)" in md             # table-of-authorities link
    assert "SHA-256" in md                        # proof hash
    assert "scholar.google.com" in md             # a real source link
    assert "login required" in md                 # subscription/bar portal label
    assert "Related authorities:" in md
    assert "Treatment:" in md


def test_html_is_wellformed_with_sections_and_crosslinks():
    htmls = embed.to_html(_packet())
    assert htmls.startswith("<!doctype html>")
    assert '<section id="auth-18-c-3-108">' in htmls
    assert 'href="#auth-18-c-3-108"' in htmls      # internal cross-link
    assert "target=\"_blank\"" in htmls            # external links open out
    assert "NOT LEGAL ADVICE" in htmls
    assert "SHA-256" in htmls


def test_render_writes_string_formats(tmp_path):
    out = tmp_path / "packet.md"
    embed.render(_packet(), "md", path=str(out))
    assert out.read_text(encoding="utf-8").startswith("# Citation Verification Packet")


def test_docx_has_bookmarks_hyperlinks_and_disclaimer(tmp_path):
    pytest.importorskip("docx")
    out = tmp_path / "authorities.docx"
    embed.to_docx(_packet(), str(out))
    assert out.exists()
    with zipfile.ZipFile(out) as z:
        xml = z.read("word/document.xml").decode("utf-8")
    assert "bookmarkStart" in xml                  # internal destinations
    assert "hyperlink" in xml                      # links
    assert "EXPERIMENTAL" in xml                   # disclaimer stamped

    from docx import Document
    doc = Document(str(out))
    texts = "\n".join(p.text for p in doc.paragraphs)
    assert "2000 ME 17" in texts


def test_pdf_is_valid_with_outline_and_links(tmp_path):
    pytest.importorskip("reportlab")
    out = tmp_path / "authorities.pdf"
    embed.to_pdf(_packet(), str(out))
    data = out.read_bytes()
    assert data.startswith(b"%PDF")
    assert b"/Outlines" in data                    # sidebar bookmarks
    assert b"/URI" in data                         # external link annotations
    assert len(data) > 1500
