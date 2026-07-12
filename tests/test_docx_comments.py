"""DOCX citation comment annotation tests."""
import xml.etree.ElementTree as ET
import zipfile

from adapters.maine.adapter import MaineProbateAdapter
from hallucheck import docx_comments

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def _minimal_docx(path, text):
    content_types = """<?xml version='1.0' encoding='UTF-8'?>
<Types xmlns='http://schemas.openxmlformats.org/package/2006/content-types'>
  <Default Extension='rels' ContentType='application/vnd.openxmlformats-package.relationships+xml'/>
  <Default Extension='xml' ContentType='application/xml'/>
  <Override PartName='/word/document.xml' ContentType='application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml'/>
</Types>"""
    rels = """<?xml version='1.0' encoding='UTF-8'?>
<Relationships xmlns='http://schemas.openxmlformats.org/package/2006/relationships'></Relationships>"""
    doc = f"""<?xml version='1.0' encoding='UTF-8'?>
<w:document xmlns:w='{W}'><w:body><w:p><w:r><w:t>{text}</w:t></w:r></w:p></w:body></w:document>"""
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("[Content_Types].xml", content_types)
        zf.writestr("word/_rels/document.xml.rels", rels)
        zf.writestr("word/document.xml", doc)


def test_annotate_docx_adds_comments_with_source_links(tmp_path):
    src = tmp_path / "brief.docx"
    out = tmp_path / "reviewed.docx"
    _minimal_docx(src, "The brief cites 18-C §3-108 and 410 U.S. 113.")

    result = docx_comments.annotate_docx(src, out, MaineProbateAdapter())

    assert result["comments_added"] == 2
    with zipfile.ZipFile(out) as zf:
        comments = zf.read("word/comments.xml").decode("utf-8")
        rels = zf.read("word/_rels/document.xml.rels").decode("utf-8")
        content_types = zf.read("[Content_Types].xml").decode("utf-8")
        document = ET.fromstring(zf.read("word/document.xml"))
    assert "18-C §3-108" in comments
    assert "410 U.S. 113" in comments
    assert "google.com" in comments or "courtlistener.com" in comments
    assert "comments.xml" in rels
    assert "/word/comments.xml" in content_types
    assert document.findall(f".//{{{W}}}commentRangeStart")
