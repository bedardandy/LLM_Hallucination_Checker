"""Document text extraction helpers for citation review workflows.

The scanner works on text, but opposing briefs and research packets often arrive
as DOCX, PDF, HTML, or Markdown.  Keep the core dependency-free by supporting
plain-text/HTML/DOCX with the standard library and using optional PDF extractors
when installed.
"""
from __future__ import annotations

import html
import pathlib
import re
import xml.etree.ElementTree as ET
import zipfile

_TEXT_SUFFIXES = {".txt", ".md", ".markdown", ".rst", ".csv", ".json", ".xml"}
_HTML_SUFFIXES = {".html", ".htm"}


def read_document(path_or_dash: str | None) -> str:
    """Read text from stdin marker or a TXT/MD/HTML/DOCX/PDF file path."""
    if not path_or_dash or path_or_dash == "-":
        import sys
        return sys.stdin.read()
    path = pathlib.Path(path_or_dash)
    suffix = path.suffix.lower()
    if suffix in _TEXT_SUFFIXES or not suffix:
        return path.read_text(encoding="utf-8")
    if suffix in _HTML_SUFFIXES:
        return html_to_text(path.read_text(encoding="utf-8"))
    if suffix == ".docx":
        return docx_to_text(path)
    if suffix == ".pdf":
        return pdf_to_text(path)
    return path.read_text(encoding="utf-8")


def html_to_text(markup: str) -> str:
    """Extract readable text from simple HTML without adding a parser dependency."""
    markup = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", markup or "")
    markup = re.sub(r"(?i)<br\s*/?>", "\n", markup)
    markup = re.sub(r"(?i)</(p|div|li|h[1-6]|tr|section|article)>", "\n", markup)
    return _collapse(html.unescape(re.sub(r"<[^>]+>", " ", markup)))


def docx_to_text(path) -> str:
    """Extract paragraphs/tables from a DOCX file using its zipped XML parts."""
    chunks: list[str] = []
    with zipfile.ZipFile(path) as zf:
        for name in sorted(n for n in zf.namelist() if n.startswith("word/") and n.endswith(".xml")):
            if not (name == "word/document.xml" or name.startswith("word/footnotes")
                    or name.startswith("word/endnotes")):
                continue
            root = ET.fromstring(zf.read(name))
            for node in root.iter():
                if node.tag.endswith("}t") and node.text:
                    chunks.append(node.text)
                elif node.tag.endswith("}p"):
                    chunks.append("\n")
    return _collapse(" ".join(chunks))


def pdf_to_text(path) -> str:
    """Extract PDF text with optional pypdf/PyPDF2 when available."""
    reader_cls = None
    try:
        from pypdf import PdfReader
        reader_cls = PdfReader
    except ImportError:
        try:
            from PyPDF2 import PdfReader
            reader_cls = PdfReader
        except ImportError as exc:
            raise RuntimeError("PDF text extraction requires optional dependency pypdf or PyPDF2") from exc
    reader = reader_cls(str(path))
    pages = [(page.extract_text() or "") for page in reader.pages]
    return _collapse("\n\n".join(pages))


def _collapse(text: str) -> str:
    lines = [re.sub(r"[ \t]+", " ", ln).strip() for ln in (text or "").splitlines()]
    return "\n".join(ln for ln in lines if ln).strip() + ("\n" if any(lines) else "")
