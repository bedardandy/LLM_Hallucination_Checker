"""Annotate DOCX legal citations with source-review comments.

The implementation edits Office Open XML directly so it works without requiring
Word or python-docx. It targets the common case where a citation appears within a
single text run; complex citations split across runs are still surfaced by the
plain scanner but are not rewritten in-place.
"""
from __future__ import annotations

import copy
import datetime
import pathlib
import xml.etree.ElementTree as ET
import zipfile

from . import scan, sources
from .documents import docx_to_text

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG_REL = "http://schemas.openxmlformats.org/package/2006/relationships"
CONTENT_TYPES = "http://schemas.openxmlformats.org/package/2006/content-types"
COMMENTS_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/comments"
COMMENTS_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.comments+xml"

ET.register_namespace("w", W)
ET.register_namespace("r", R)
ET.register_namespace("", CONTENT_TYPES)


def citation_review_records(adapter, text: str, *, scope: str | None = None) -> list[dict]:
    """Return citation hits plus source/search links suitable for DOCX comments."""
    rep = scan.report(text or "", adapter, scope=scope)
    vocab = adapter.build_vocabulary(scope) if hasattr(adapter, "build_vocabulary") else {}
    records: list[dict] = []
    for h in rep.get("hits", []):
        cite = h["cite"]
        meta = {"cite": cite, **(vocab.get(cite) or {}), "kind": h.get("kind")}
        records.append({"cite": cite, "span": h["span"], "class": "adapter",
                        "resolves": h.get("resolves"), "links": sources.for_citation(meta)})
    for h in rep.get("generic_hits", []):
        cite = h["cite"]
        records.append({"cite": cite, "span": h["span"], "class": "unclassified",
                        "resolves": False, "links": sources.for_citation({"cite": cite, "kind": h.get("kind")})})
    return records


def annotate_docx(input_path, output_path, adapter, *, scope: str | None = None,
                  author: str = "hallucheck", initials: str = "HC", limit: int = 200) -> dict:
    """Copy ``input_path`` to ``output_path`` and add comments for legal citations.

    Each comment includes direct/free source links where available plus research
    portal prompts (Westlaw/Lexis/bar-member platforms) with the citation query to
    paste after login. Returns ``{input, output, comments_added, citations}``.
    """
    input_path, output_path = pathlib.Path(input_path), pathlib.Path(output_path)
    with zipfile.ZipFile(input_path, "r") as zin:
        entries = {info.filename: zin.read(info.filename) for info in zin.infolist()}

    root = ET.fromstring(entries["word/document.xml"])
    parent = {child: p for p in root.iter() for child in list(p)}
    comments_root, next_id = _load_comments_from_entries(entries)
    records_added: list[dict] = []

    for t in list(root.iter(_q("t"))):
        if len(records_added) >= limit:
            break
        text = t.text or ""
        matches = citation_review_records(adapter, text, scope=scope)
        if not matches:
            continue
        run = parent.get(t)
        para = parent.get(run) if run is not None else None
        if run is None or para is None:
            continue
        idx = list(para).index(run)
        replacement = _replacement_runs(text, matches, comments_root, next_id,
                                         author=author, initials=initials)
        if not replacement:
            continue
        records_added.extend(replacement["records"])
        next_id = replacement["next_id"]
        para.remove(run)
        for offset, node in enumerate(replacement["nodes"]):
            para.insert(idx + offset, node)

    if records_added:
        entries["word/comments.xml"] = _xml(comments_root)
        entries["word/_rels/document.xml.rels"] = _comments_rel_xml(entries)
        entries["[Content_Types].xml"] = _comments_content_type_xml(entries)
        entries["word/document.xml"] = _xml(root)

    with zipfile.ZipFile(output_path, "w") as zout:
        for name, data in entries.items():
            zout.writestr(name, data)

    return {"input": str(input_path), "output": str(output_path),
            "comments_added": len(records_added),
            "citations": records_added, "document_text_chars": len(docx_to_text(output_path))}


def _replacement_runs(text: str, matches: list[dict], comments_root, next_id: int, *,
                      author: str, initials: str) -> dict | None:
    nodes = []
    records = []
    pos = 0
    for m in matches:
        start, end = m["span"]
        if start < pos:
            continue
        if start > pos:
            nodes.append(_run(text[pos:start]))
        cid = str(next_id); next_id += 1
        cite_text = text[start:end]
        _append_comment(comments_root, cid, _comment_text(m), author=author, initials=initials)
        nodes.extend([_comment_range_start(cid), _run(cite_text), _comment_range_end(cid),
                      _comment_ref(cid)])
        records.append({"id": cid, "cite": m["cite"], "class": m["class"],
                        "resolves": m["resolves"]})
        pos = end
    if pos < len(text):
        nodes.append(_run(text[pos:]))
    return {"nodes": nodes, "records": records, "next_id": next_id} if records else None


def _comment_text(record: dict) -> str:
    bundle = record["links"]
    lines = [f"hallucheck: verify {record['cite']} ({record['class']})."]
    if record["class"] == "unclassified":
        lines.append("This citation is not resolved by the active adapter; confirm in a trusted platform.")
    for ln in bundle.get("links", [])[:5]:
        url = ln.get("url") or ln.get("view_url") or ln.get("portal_url")
        if url:
            lines.append(f"{ln.get('label')}: {url}")
    if bundle.get("portals"):
        lines.append("Research platforms (login may be required):")
        for p in bundle["portals"][:4]:
            lines.append(f"{p['label']}: {p['portal_url']} — search: {p['query']}")
    return "\n".join(lines)


def _load_comments_from_entries(entries: dict[str, bytes]) -> tuple[ET.Element, int]:
    raw = entries.get("word/comments.xml")
    root = ET.fromstring(raw) if raw else ET.Element(_q("comments"))
    ids = [int(c.attrib.get(_q("id"), "-1")) for c in root.findall(_q("comment"))]
    return root, (max(ids) + 1 if ids else 0)


def _append_comment(root, cid: str, text: str, *, author: str, initials: str) -> None:
    c = ET.SubElement(root, _q("comment"), {_q("id"): cid, _q("author"): author,
                                             _q("initials"): initials,
                                             _q("date"): datetime.datetime.now(datetime.timezone.utc).isoformat()})
    p = ET.SubElement(c, _q("p"))
    r = ET.SubElement(p, _q("r"))
    t = ET.SubElement(r, _q("t"))
    t.text = text


def _run(text: str) -> ET.Element:
    r = ET.Element(_q("r"))
    t = ET.SubElement(r, _q("t"))
    if text.startswith(" ") or text.endswith(" "):
        t.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
    t.text = text
    return r


def _comment_range_start(cid: str) -> ET.Element:
    return ET.Element(_q("commentRangeStart"), {_q("id"): cid})


def _comment_range_end(cid: str) -> ET.Element:
    return ET.Element(_q("commentRangeEnd"), {_q("id"): cid})


def _comment_ref(cid: str) -> ET.Element:
    r = ET.Element(_q("r"))
    ET.SubElement(r, _q("commentReference"), {_q("id"): cid})
    return r


def _comments_rel_xml(entries: dict[str, bytes]) -> bytes:
    path = "word/_rels/document.xml.rels"
    raw = entries.get(path)
    root = ET.fromstring(raw) if raw else ET.Element(f"{{{PKG_REL}}}Relationships")
    for rel in root.findall(f"{{{PKG_REL}}}Relationship"):
        if rel.attrib.get("Type") == COMMENTS_REL:
            return _xml(root)
    ids = [rel.attrib.get("Id", "") for rel in root.findall(f"{{{PKG_REL}}}Relationship")]
    rid = _next_rid(ids)
    ET.SubElement(root, f"{{{PKG_REL}}}Relationship",
                  {"Id": rid, "Type": COMMENTS_REL, "Target": "comments.xml"})
    return _xml(root)


def _comments_content_type_xml(entries: dict[str, bytes]) -> bytes:
    root = ET.fromstring(entries["[Content_Types].xml"])
    for ov in root.findall(f"{{{CONTENT_TYPES}}}Override"):
        if ov.attrib.get("PartName") == "/word/comments.xml":
            return _xml(root)
    ET.SubElement(root, f"{{{CONTENT_TYPES}}}Override",
                  {"PartName": "/word/comments.xml", "ContentType": COMMENTS_CONTENT_TYPE})
    return _xml(root)



def _next_rid(ids: list[str]) -> str:
    nums = [int(i[3:]) for i in ids if i.startswith("rId") and i[3:].isdigit()]
    return f"rId{(max(nums) + 1) if nums else 1}"


def _q(local: str) -> str:
    return f"{{{W}}}{local}"


def _xml(root: ET.Element) -> bytes:
    return ET.tostring(copy.deepcopy(root), encoding="utf-8", xml_declaration=True)
