"""Document extraction tests for citation review inputs."""
import zipfile

from hallucheck.documents import docx_to_text, html_to_text, read_document


def test_html_to_text_strips_markup_and_scripts():
    text = html_to_text("<html><script>hide()</script><p>See <b>42 U.S.C. § 1983</b>.</p></html>")
    assert "42 U.S.C. § 1983" in text
    assert "hide()" not in text


def test_read_document_handles_markdown(tmp_path):
    draft = tmp_path / "brief.md"
    draft.write_text("# Brief\n\nSee Fed. R. Civ. P. 56.", encoding="utf-8")
    assert "Fed. R. Civ. P. 56" in read_document(str(draft))


def test_docx_to_text_uses_zipped_document_xml(tmp_path):
    docx = tmp_path / "brief.docx"
    xml = """<?xml version='1.0' encoding='UTF-8' standalone='yes'?>
    <w:document xmlns:w='http://schemas.openxmlformats.org/wordprocessingml/2006/main'>
      <w:body><w:p><w:r><w:t>Opposition cites 410 U.S. 113.</w:t></w:r></w:p></w:body>
    </w:document>"""
    with zipfile.ZipFile(docx, "w") as zf:
        zf.writestr("word/document.xml", xml)
    assert "410 U.S. 113" in docx_to_text(docx)
