#!/usr/bin/env python3
"""Ingestion pipeline: validate -> parse -> normalize -> chunk -> diff -> persist.

    python parse.py <file> <outdir> [--previous <previous-normalized.json>]

Stages (per ../inital_docs/knowledge/ingestion.md):
  1. Document Validation  (validate.py) -- fail fast with a clear reason;
     failures persist a FAILED artifact and exit(1).
  2. Parsing -- anydoc's shared document model for office formats; PDF and
     Markdown inputs go through Markdown structure recovery (headings,
     tables, lists) instead of being flattened to one paragraph.
  3. Normalization -- Unicode NFKC + glyph cleanup, boilerplate & duplicate
     detection (headers/footers, page numbers, repeated notices).
  4. Structure extraction -- heading hierarchy + reading sequence.
  5. Structure-aware chunking (chunk.py) -- token budget, overlap, section
     provenance, content hashes (version-diff keys).
  6. Version diff (optional, --previous) -- chunk hash comparison ->
     unchanged / changed / added / removed.
  7. Persist normalized_document_v2 artifact + JSON summary on stdout.

Output schema: ``normalized_document_v2``. Pipeline: ``structure_aware_v3``.
This is the Python implementation; the JSON contract and chunk content hashes
are identical to the earlier JavaScript pipeline, so ``--previous`` diffing
works across both.
"""

import argparse
import hashlib
import json
import os
import re
import sys
from datetime import UTC, datetime

from app.knowledge.ingestion.chunk import (
    HIERARCHICAL_CHUNKER_VERSION,
    hierarchical_chunk,
)
from app.knowledge.ingestion.chunk import (
    config as chunk_config,
)
from app.knowledge.ingestion.normalize import (
    block_plain_text,
    detect_boilerplate,
    normalize_blocks,
    normalize_unicode,
)
from app.knowledge.ingestion.validate import VALIDATION_VERSION, validate_and_parse

PARSER_VERSION = "anydoc-0.1.3"
PIPELINE_VERSION = "structure_aware_v3"
SCHEMA = "normalized_document_v2"


class IngestionFailed(Exception):
    """Raised by :func:`parse_file` / :func:`build_normalized` after the
    FAILED artifact is persisted (parse_file) or the failure is classified
    (worker).

    Carries the validation code, reason, and the full validation checks so
    callers can persist a FAILED artifact or record a failure reason.
    :func:`main` maps it to exit code 1. Raising (rather than calling
    ``sys.exit``) keeps ``parse_file`` unit-testable.
    """

    def __init__(self, code, reason, checks=None):
        super().__init__(f"{code}: {reason}")
        self.code = code
        self.reason = reason
        self.checks = checks or {}


class ChunkingError(IngestionFailed):
    """Raised when structure-aware chunking fails (maps to ``CHUNKING_ERROR``).

    Distinct from validation/parse failures so the worker can record the
    coarse failure reason the ``ingestion_job.failure_reason`` enum expects.
    """

    def __init__(self, reason, checks=None):
        super().__init__("CHUNKING_FAILED", reason, checks=checks)


def sha256(data):
    if isinstance(data, bytes):
        return hashlib.sha256(data).hexdigest()
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# anydoc document model -> normalized JSON block shape
# ---------------------------------------------------------------------------

def inline_to_dict(inl):
    kind = inl.kind
    if kind == "text":
        style = inl.style
        s = {}
        if style:
            if style.bold:
                s["bold"] = True
            if style.italic:
                s["italic"] = True
            if style.strike:
                s["strike"] = True
            if style.code:
                s["code"] = True
        d = {"type": "text", "text": normalize_unicode(inl.text)}
        if s:
            d["style"] = s
        return d
    if kind == "link":
        return {
            "type": "link",
            "target": {"kind": inl.target.kind, "value": inl.target.value},
            "content": [inline_to_dict(i) for i in (inl.content or [])],
        }
    if kind == "image":
        src = {"kind": inl.source.kind}
        if inl.source.url:
            src["url"] = inl.source.url
        if inl.source.asset_id is not None:
            src["asset_id"] = inl.source.asset_id
        return {"type": "image", "alt": normalize_unicode(inl.alt), "source": src}
    if kind == "anchor":
        return {"type": "anchor", "anchor": inl.anchor}
    if kind == "note_ref":
        return {"type": "note_ref", "note_id": inl.note_id}
    if kind == "line_break":
        return {"type": "line_break"}
    return {"type": "unknown", "kind": kind}


def cell_slot_to_dict(slot):
    if slot.kind == "origin":
        cell = slot.cell
        return {
            "kind": "origin",
            "cell": {
                "col_span": cell.col_span,
                "row_span": cell.row_span,
                "blocks": [block_to_dict(b) for b in cell.blocks],
            },
        }
    return {"kind": "covered", "origin_row": slot.origin_row, "origin_col": slot.origin_col}


def block_to_dict(block):
    kind = block.kind
    if kind == "heading":
        d = {"type": "heading", "level": block.level}
        if block.anchor:
            d["anchor"] = block.anchor
        d["content"] = [inline_to_dict(i) for i in (block.content or [])]
        return d
    if kind == "paragraph":
        return {"type": "paragraph", "content": [inline_to_dict(i) for i in (block.content or [])]}
    if kind == "list":
        items = []
        for item in block.list.items:
            it = {"blocks": [block_to_dict(b) for b in item.blocks]}
            if item.checked is not None:
                it["checked"] = item.checked
            if item.marker_label:
                it["marker_label"] = item.marker_label
            items.append(it)
        return {"type": "list", "marker": block.list.marker, "start": block.list.start, "items": items}
    if kind == "table":
        return {
            "type": "table",
            "kind": block.table.kind,
            "header_rows": block.table.header_rows,
            "grid": [[cell_slot_to_dict(s) for s in row] for row in block.table.grid],
        }
    if kind == "block_quote":
        return {"type": "block_quote", "blocks": [block_to_dict(b) for b in (block.blocks or [])]}
    if kind == "code_block":
        d = {"type": "code_block"}
        if block.lang:
            d["lang"] = block.lang
        d["text"] = block.text or ""
        return d
    if kind == "rule":
        return {"type": "rule"}
    return {"type": "unknown", "kind": kind}


# ---------------------------------------------------------------------------
# Markdown -> blocks (structure recovery for PDF and .md inputs)
# ---------------------------------------------------------------------------
#
# PDF and Markdown inputs arrive as Markdown text (anydoc converts PDFs to
# Markdown; .md files are read directly). Rather than flattening that text
# into paragraphs, we recover structure here: headings (ATX + setext), fenced
# code blocks, pipe tables, blockquotes (recursive, incl. lazy paragraph
# continuation), bullet/ordered/task lists nested by indentation, thematic
# breaks, and paragraphs. Inline content (bold/italic/code/strike/links/
# images) is parsed into the same inline dict shape the anydoc document model
# produces, so normalization, chunking, and boilerplate detection treat every
# input identically.

FENCE_RE = re.compile(r"^\s*(```+|~~~+)\s*([^\s`]*)\s*$")
HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
SETEXT_H1_RE = re.compile(r"^\s*={2,}\s*$")
SETEXT_H2_RE = re.compile(r"^\s*-{2,}\s*$")
HR_RE = re.compile(r"^\s*([-*_])(?:\s*\1){2,}\s*$")
TABLE_DIVIDER_RE = re.compile(r"^\s*\|[\s|:-]+\|\s*$")
BLOCKQUOTE_RE = re.compile(r"^\s*>\s?(.*)$")
LIST_MARKER_RE = re.compile(r"^(\s*)([-*+]|\d{1,9}[.)])\s+(.*)$")
TASK_MARKER_RE = re.compile(r"^\[([ xX])\]\s*(.*)$")
URL_SCHEME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.\-]*://")

# Recursion caps for nested blockquotes / emphasis on adversarial input.
MAX_MARKDOWN_DEPTH = 32


def link_target_kind(value):
    """Classify a link target per the document model's LinkTarget kinds."""
    if URL_SCHEME_RE.match(value):
        return "external"
    if value.startswith("#"):
        return "anchor"
    return "relative"


def _with_style(inlines, style):
    """Merge ``style`` into every text inline (nested emphasis support).

    Links are styled through their content so ``**[x](u)**`` keeps bold."""
    merged = []
    for inl in inlines:
        if inl.get("type") == "text":
            s = dict(inl.get("style") or {})
            s.update(style)
            merged.append({**inl, "style": s})
        elif inl.get("type") == "link":
            merged.append({**inl, "content": _with_style(inl.get("content", []), style)})
        else:
            merged.append(inl)
    return merged


def parse_inlines(text, _depth=0):
    """Parse Markdown inline formatting into inline dicts.

    Supports ``**bold**``, ``*italic*``, ``_italic_`` (not mid-word),
    `` `code` ``, ``~~strike~~``, ``[text](url)`` links, ``![alt](url)``
    images, and ``\\`` escapes. Bold/italic/strike spans are re-parsed so
    nested emphasis survives; code spans stay literal.
    """
    if _depth > MAX_MARKDOWN_DEPTH:
        return [{"type": "text", "text": text}]
    out = []
    i, n = 0, len(text)
    while i < n:
        ch = text[i]

        if ch == "\\" and i + 1 < n:
            out.append({"type": "text", "text": text[i : i + 2]})
            i += 2
            continue

        if ch == "`":
            end = text.find("`", i + 1)
            if end != -1 and text[i + 1 : end].strip():
                out.append({"type": "text", "text": text[i + 1 : end], "style": {"code": True}})
                i = end + 1
                continue

        if ch == "!" and text.startswith("![", i):
            end = text.find("]", i + 2)
            if end != -1 and text[end + 1 : end + 2] == "(":
                url_end = text.find(")", end + 2)
                if url_end != -1:
                    url = text[end + 2 : url_end]
                    out.append(
                        {
                            "type": "image",
                            "alt": text[i + 2 : end],
                            "source": {"kind": link_target_kind(url), "url": url},
                        }
                    )
                    i = url_end + 1
                    continue

        if ch == "[":
            end = text.find("]", i + 1)
            if end != -1 and text[end + 1 : end + 2] == "(":
                url_end = text.find(")", end + 2)
                if url_end != -1:
                    url = text[end + 2 : url_end]
                    out.append(
                        {
                            "type": "link",
                            "target": {"kind": link_target_kind(url), "value": url},
                            "content": parse_inlines(text[i + 1 : end], _depth + 1),
                        }
                    )
                    i = url_end + 1
                    continue

        if text.startswith("~~", i):
            end = text.find("~~", i + 2)
            if end != -1 and text[i + 2 : end].strip():
                out.extend(_with_style(parse_inlines(text[i + 2 : end], _depth + 1), {"strike": True}))
                i = end + 2
                continue

        if text.startswith("**", i):
            end = text.find("**", i + 2)
            if end != -1 and text[i + 2 : end].strip():
                out.extend(_with_style(parse_inlines(text[i + 2 : end], _depth + 1), {"bold": True}))
                i = end + 2
                continue

        if ch == "*":
            end = text.find("*", i + 1)
            if end != -1 and text[i + 1 : end].strip():
                out.extend(_with_style(parse_inlines(text[i + 1 : end], _depth + 1), {"italic": True}))
                i = end + 1
                continue

        if ch == "_":
            prev = text[i - 1] if i > 0 else ""
            if not (prev and (prev.isalnum() or prev == "_")):
                end = text.find("_", i + 1)
                if end != -1 and text[i + 1 : end].strip():
                    out.extend(_with_style(parse_inlines(text[i + 1 : end], _depth + 1), {"italic": True}))
                    i = end + 1
                    continue

        j = i + 1
        while j < n and text[j] not in "*_`[~!\\":
            j += 1
        if j == i:
            j = i + 1
        out.append({"type": "text", "text": text[i:j]})
        i = j

    # Merge adjacent plain text inlines of equal style (e.g. "foo" + "_bar"
    # when an underscore falls mid-word and is treated as literal).
    merged = []
    for inl in out:
        if (
            merged
            and inl.get("type") == "text"
            and merged[-1].get("type") == "text"
            and merged[-1].get("style") == inl.get("style")
        ):
            merged[-1] = {**merged[-1], "text": merged[-1]["text"] + inl["text"]}
        else:
            merged.append(inl)
    return merged


def _append_list_item(lst, text, checked):
    """Add one list item (paragraph + optional task checkbox) to ``lst``."""
    item = {"blocks": []}
    if text:
        item["blocks"].append(
            {"type": "paragraph", "content": parse_inlines(normalize_unicode(text))}
        )
    if checked is not None:
        item["checked"] = checked
    lst["items"].append(item)
    return item


def parse_markdown(md, _depth=0):
    """Recover structure from Markdown text (PDF and ``.md`` inputs).

    Line-based parser handling ATX + setext headings, fenced code blocks,
    pipe tables, blockquotes (recursive, incl. lazy paragraph continuation),
    bullet/ordered/task lists nested by indentation, thematic breaks, and
    paragraphs. Inline content goes through :func:`parse_inlines`.
    """
    blocks = []
    lines = md.splitlines()
    paragraph = []        # pending raw lines of a top-level paragraph
    code_buffer = None    # raw lines inside a fenced code block
    code_lang = None
    table = None          # accumulated table rows
    quote_lines = None    # pending blockquote lines
    list_stack = []       # open lists: {"indent", "list", "open_item"}
    after_blank = True    # blank line since the last content line

    def target_for_block():
        """Where a completed block should go (inside the open list item if any)."""
        if list_stack and list_stack[-1]["open_item"] is not None:
            return list_stack[-1]["open_item"]["blocks"]
        return blocks

    def flush_paragraph():
        nonlocal paragraph
        if not paragraph:
            return
        text = " ".join(p.strip() for p in paragraph).strip()
        paragraph = []
        if text:
            target_for_block().append(
                {"type": "paragraph", "content": parse_inlines(normalize_unicode(text))}
            )

    def flush_table():
        nonlocal table
        if table:
            target_for_block().append(table)
            table = None

    def flush_code():
        nonlocal code_buffer, code_lang
        if code_buffer is not None:
            d = {"type": "code_block", "text": code_buffer}
            if code_lang:
                d["lang"] = code_lang
            target_for_block().append(d)
            code_buffer = None
            code_lang = None

    def close_quote():
        nonlocal quote_lines
        if quote_lines is not None:
            inner = "\n".join(quote_lines)
            quote_lines = None
            if _depth >= MAX_MARKDOWN_DEPTH:
                # Guard against unbounded recursion on adversarial nesting;
                # fall back to a plain paragraph.
                text = " ".join(l.strip() for l in inner.splitlines()).strip()
                if text:
                    target_for_block().append(
                        {"type": "paragraph", "content": parse_inlines(normalize_unicode(text))}
                    )
            else:
                parsed = parse_markdown(inner, _depth + 1)
                if parsed:
                    target_for_block().append({"type": "block_quote", "blocks": parsed})

    def close_lists():
        nonlocal list_stack
        list_stack = []

    for line in lines:
        # 1. Inside a fenced code block: accumulate until the closing fence.
        if code_buffer is not None:
            if FENCE_RE.match(line):
                flush_code()
            else:
                code_buffer += line + "\n"
            continue

        # 2. Fence opener.
        fence = FENCE_RE.match(line)
        if fence:
            flush_paragraph()
            close_lists()
            flush_table()
            close_quote()
            code_buffer = ""
            code_lang = fence.group(2) or None
            continue

        # 3. Blank line: flush pending paragraph, end quotes; lists stay open.
        if not line.strip():
            flush_paragraph()
            flush_table()
            close_quote()
            after_blank = True
            continue

        # 4. Blockquote: consecutive "> " lines accumulate; a bare ">" keeps
        #    the quote open across a blank line.
        quote_m = BLOCKQUOTE_RE.match(line)
        if quote_m:
            flush_paragraph()
            flush_table()
            if quote_lines is None:
                quote_lines = []
            quote_lines.append(quote_m.group(1))
            after_blank = False
            continue

        # 5. Headings (ATX).
        heading_m = HEADING_RE.match(line)
        if heading_m:
            flush_paragraph()
            close_lists()
            flush_table()
            close_quote()
            blocks.append(
                {
                    "type": "heading",
                    "level": len(heading_m.group(1)),
                    "content": parse_inlines(normalize_unicode(heading_m.group(2))),
                }
            )
            after_blank = False
            continue

        # 6. Setext headings: "===" / "---" directly under a paragraph line.
        if SETEXT_H1_RE.match(line) and paragraph:
            text = " ".join(p.strip() for p in paragraph)
            paragraph = []
            close_lists()
            blocks.append(
                {"type": "heading", "level": 1, "content": parse_inlines(normalize_unicode(text))}
            )
            after_blank = False
            continue
        if SETEXT_H2_RE.match(line) and paragraph:
            text = " ".join(p.strip() for p in paragraph)
            paragraph = []
            close_lists()
            blocks.append(
                {"type": "heading", "level": 2, "content": parse_inlines(normalize_unicode(text))}
            )
            after_blank = False
            continue

        # 7. Thematic break.
        if HR_RE.match(line):
            flush_paragraph()
            close_lists()
            flush_table()
            close_quote()
            blocks.append({"type": "rule"})
            after_blank = False
            continue

        # 8. Tables: divider row separates header from data; rows accumulate.
        if TABLE_DIVIDER_RE.match(line):
            flush_paragraph()
            close_lists()
            after_blank = False
            continue
        if re.match(r"^\s*\|", line):
            flush_paragraph()
            close_lists()
            close_quote()
            cells = [c.strip() for c in line.strip().lstrip("|").rstrip("|").split("|")]
            if table is None:
                table = {"type": "table", "kind": "data", "header_rows": 1, "grid": []}
            table["grid"].append(
                [
                    {
                        "kind": "origin",
                        "cell": {
                            "col_span": 1,
                            "row_span": 1,
                            "blocks": [
                                {
                                    "type": "paragraph",
                                    "content": parse_inlines(normalize_unicode(c)),
                                }
                            ],
                        },
                    }
                    for c in cells
                ]
            )
            after_blank = False
            continue

        # 9. Lists: bullet / ordered / task markers, nested by indentation.
        list_m = LIST_MARKER_RE.match(line)
        if list_m:
            flush_paragraph()
            flush_table()
            close_quote()
            after_blank = False
            indent = len(list_m.group(1))
            marker = list_m.group(2)
            text = list_m.group(3)
            ordered = marker[-1] in ".)"
            start = int(marker.rstrip(".)")) if ordered else 1
            checked = None
            task_m = TASK_MARKER_RE.match(text)
            if task_m:
                checked = task_m.group(1).lower() == "x"
                text = task_m.group(2)
            while list_stack and list_stack[-1]["indent"] > indent:
                list_stack.pop()
            if list_stack and list_stack[-1]["indent"] < indent:
                # Deeper indent: a nested list inside the current item.
                lst = {"type": "list", "marker": "ordered" if ordered else "bullet",
                       "start": start, "items": []}
                item = _append_list_item(lst, text, checked)
                list_stack[-1]["open_item"]["blocks"].append(lst)
                list_stack.append({"indent": indent, "list": lst, "open_item": item})
            elif list_stack and list_stack[-1]["indent"] == indent:
                lst = list_stack[-1]["list"]
                item = _append_list_item(lst, text, checked)
                list_stack[-1]["open_item"] = item
            else:
                lst = {"type": "list", "marker": "ordered" if ordered else "bullet",
                       "start": start, "items": []}
                item = _append_list_item(lst, text, checked)
                target_for_block().append(lst)
                list_stack.append({"indent": indent, "list": lst, "open_item": item})
            continue

        # 10. Paragraph. Inside a list item, continuation lines merge into the
        #     item's paragraph; after a blank line (or at a shallower indent)
        #     the list closes and the paragraph goes top-level. A non-quote
        #     line right after a quote lazily continues the quote's paragraph.
        line_indent = len(line) - len(line.lstrip())
        if list_stack and (after_blank or line_indent < list_stack[-1]["indent"]):
            close_lists()
        if quote_lines is not None:
            quote_lines.append(line)
        elif list_stack and list_stack[-1]["open_item"] is not None:
            item = list_stack[-1]["open_item"]
            if item["blocks"] and item["blocks"][-1].get("type") == "paragraph":
                item["blocks"][-1]["content"].extend(
                    [{"type": "text", "text": " "}] + parse_inlines(normalize_unicode(line.strip()))
                )
            else:
                item["blocks"].append(
                    {"type": "paragraph", "content": parse_inlines(normalize_unicode(line.strip()))}
                )
        else:
            paragraph.append(line)
        after_blank = False

    flush_paragraph()
    flush_table()
    flush_code()
    close_quote()
    return blocks

# ---------------------------------------------------------------------------
# Structure extraction
# ---------------------------------------------------------------------------

def heading_text(inlines):
    return block_plain_text({"type": "heading", "content": inlines})


def build_heading_hierarchy(blocks):
    headings = [b for b in blocks if b.get("type") == "heading"]
    tree = []
    stack = []
    for h in headings:
        node = {"level": h.get("level"), "text": heading_text(h.get("content")), "children": []}
        while stack and stack[-1]["level"] >= h.get("level", 1):
            stack.pop()
        if not stack:
            tree.append(node)
        else:
            stack[-1]["children"].append(node)
        stack.append(node)
    return tree


def build_reading_sequence(blocks, boilerplate):
    sequence = []
    for i, b in enumerate(blocks):
        section = None
        for j in range(i, -1, -1):
            if blocks[j].get("type") == "heading":
                section = heading_text(blocks[j].get("content"))
                break
        flag = boilerplate[i] if boilerplate else None
        entry = {
            "seq": len(sequence),
            "type": b.get("type"),
            "section": section or None,
        }
        if flag:
            entry["boilerplate"] = True
            entry["boilerplate_kind"] = flag["kind"]
        if b.get("type") == "heading":
            entry["level"] = b.get("level")
            entry["text"] = heading_text(b.get("content"))
        if b.get("type") in ("paragraph", "heading"):
            entry["plain_text"] = block_plain_text(b)
        if b.get("type") == "table":
            grid = b.get("grid", [])
            entry["rows"] = len(grid)
            entry["cols"] = len(grid[0]) if grid else 0
        if b.get("type") == "code_block":
            entry["text"] = b.get("text")
        sequence.append(entry)
    return sequence


def count_blocks(blocks, counts=None):
    if counts is None:
        counts = {}
    for b in blocks:
        t = b.get("type")
        counts[t] = counts.get(t, 0) + 1
        if t == "list":
            for it in b.get("items", []):
                count_blocks(it.get("blocks"), counts)
        if t == "block_quote":
            count_blocks(b.get("blocks"), counts)
        if t == "table":
            for row in b.get("grid", []):
                for s in row:
                    if s.get("kind") == "origin":
                        count_blocks(s["cell"].get("blocks"), counts)
    return counts


def plain_text_of_blocks(blocks):
    return "\n".join(block_plain_text(b) for b in blocks).strip()


# ---------------------------------------------------------------------------
# Version diff (chunk-hash comparison, challenge #9)
# ---------------------------------------------------------------------------

def diff_versions(prev_chunks, new_chunks):
    prev_hashes = {c["content_hash_sha256"] for c in prev_chunks}
    stats = {"unchanged": 0, "changed": 0, "added": 0, "removed": 0}
    new_hashes = set()

    for i, c in enumerate(new_chunks):
        if c["content_hash_sha256"] in prev_hashes:
            c["change"] = "unchanged"
            stats["unchanged"] += 1
        elif (
            i < len(prev_chunks)
            and prev_chunks[i]["content_hash_sha256"] != c["content_hash_sha256"]
        ):
            c["change"] = "changed"
            stats["changed"] += 1
        else:
            c["change"] = "added"
            stats["added"] += 1
        new_hashes.add(c["content_hash_sha256"])

    removed = [
        {
            "chunk_index": c["chunk_index"],
            "content_hash_sha256": c["content_hash_sha256"],
            "section_path": c.get("section_path"),
            "parent_section": c.get("parent_section"),
        }
        for c in prev_chunks
        if c["content_hash_sha256"] not in new_hashes
    ]
    stats["removed"] = len(removed)
    return stats, removed


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

def build_normalized(data, *, filename, file_path=None, previous_artifact=None):
    """Run the pipeline in memory: validate -> parse -> normalize -> chunk
    (-> optional version diff), returning the ``normalized_document_v2`` dict.

    Unlike :func:`parse_file`, nothing is written to disk and nothing is
    printed: the worker persists the returned dict through the Postgres
    persist adapter. Raises :exc:`IngestionFailed` (carrying ``checks``) when
    validation or structure checks fail, or :exc:`ChunkingError` when the
    structure-aware chunker fails, so the caller can classify the failure.
    """
    content_hash = sha256(data)

    # Stage 1 -- validation (probe parse doubles as the parse).
    validation = validate_and_parse(data, file_path=file_path)
    format_ = validation["format"]

    if not validation["ok"]:
        raise IngestionFailed(
            validation["code"], validation["reason"], checks=validation["checks"]
        )

    # Stage 2 -- parse into normalized blocks.
    parsed = validation["parsed"]
    if parsed["kind"] == "markdown":
        blocks = parse_markdown(parsed["markdown"])
        notes, assets, _document_model = [], [], False
    else:
        doc = parsed["document"]
        blocks = [block_to_dict(b) for b in doc.blocks]
        notes = [
            {"id": n.id, "kind": n.kind, "blocks": [block_to_dict(b) for b in n.blocks]}
            for n in doc.notes
        ]
        assets = [
            {"id": a.id, "media_type": a.media_type, "origin_part": a.origin_part, "bytes": len(a.data)}
            for a in doc.assets
        ]
        _document_model = True

    # Stage 3 -- normalization & boilerplate/duplicate detection.
    blocks = normalize_blocks(blocks)
    boilerplate = detect_boilerplate(blocks)
    boilerplate_summary = {"page_number": 0, "repeated": 0, "duplicate": 0}
    for f in boilerplate:
        if f:
            boilerplate_summary[f["kind"]] += 1
    # Every flagged block (page numbers, repeated headers/footers, later
    # duplicates) is excluded from chunking; first occurrences of duplicates
    # are unflagged and therefore kept.
    excluded_from_chunks = (
        boilerplate_summary["page_number"]
        + boilerplate_summary["repeated"]
        + boilerplate_summary["duplicate"]
    )

    plain_text_length = len(plain_text_of_blocks(blocks))

    # Stage 3b -- extractable-text / structural-quality checks (validation tail).
    try:
        min_chars = int(os.environ.get("INGEST_MIN_EXTRACTABLE_CHARS", "1")) or 1
    except ValueError:
        min_chars = 1
    if plain_text_length < min_chars:
        validation["checks"]["extractable_text"] = {
            "ok": False,
            "detail": f"no extractable text ({plain_text_length} chars)",
        }
        raise IngestionFailed(
            "NO_EXTRACTABLE_TEXT",
            f"no extractable text ({plain_text_length} chars)",
            checks=validation["checks"],
        )
    validation["checks"]["extractable_text"] = {
        "ok": True,
        "detail": f"{plain_text_length} chars",
    }
    validation["checks"]["structural_quality"] = {
        "ok": True,
        "detail": (
            f"{len(blocks)} blocks, "
            f"{boilerplate_summary['repeated'] + boilerplate_summary['page_number'] + boilerplate_summary['duplicate']}"
            " flagged boilerplate/duplicate"
        ),
    }

    # Stage 4 -- structure extraction (attach seq + boilerplate to top-level blocks).
    seq = build_reading_sequence(blocks, boilerplate)
    for i, b in enumerate(blocks):
        b["_seq"] = i
        b["_boilerplate"] = bool(boilerplate[i] and boilerplate[i]["boilerplate"])
        if boilerplate[i]:
            b["boilerplate"] = {"kind": boilerplate[i]["kind"], "count": boilerplate[i]["count"]}

    # Stage 5 -- hierarchical, structure-aware chunking (small-to-big).
    #
    # Builds a document -> section -> leaf tree. Only leaf rows are embedded
    # (searchable + BM25-indexed); section/document rows are the "bigger
    # context" a query expands into via parent_chunk_id. Embedding cost
    # therefore scales with content, not hierarchy depth.
    try:
        chunks = hierarchical_chunk(blocks)
    except Exception as exc:  # defensive: the chunker is pure/deterministic
        raise ChunkingError(str(exc), checks=validation["checks"]) from exc

    # Embeddable rows (leaves) are what re-embedding and version diffing key
    # on; context rows (document/section) are derived text and are skipped.
    embeddable_chunks = [c for c in chunks if c.get("embeddable")]

    # Everything extracted may still be flagged boilerplate (e.g. a document of
    # pure repeated header pages). An empty leaf set means nothing to embed,
    # so fail rather than silently marking the version INDEXED.
    if not embeddable_chunks:
        raise IngestionFailed(
            "NO_INDEXABLE_CONTENT",
            f"all {len(blocks)} blocks were flagged as boilerplate/duplicate and excluded from chunking",
            checks=validation["checks"],
        )

    # Stage 6 -- version diff (optional). Chunk hashes are compared at the
    # embeddable (leaf) level: that is exactly the set re-embedding would
    # touch, so unchanged leaves can skip re-embedding. Context (section/
    # document) rows are derived from the leaves and are never diffed.
    version_diff = None
    if previous_artifact is not None:
        prev = previous_artifact
        prev_leaves = [c for c in (prev.get("chunks") or []) if c.get("embeddable", True)]
        stats, removed_chunks = diff_versions(prev_leaves, embeddable_chunks)
        version_diff = {
            "strategy": "chunk_hash_v1",
            "previous_schema": prev.get("schema"),
            "previous_file": (prev.get("metadata") or {}).get("original_filename"),
            "stats": stats,
            "removed_chunks": removed_chunks,
        }

    title_heading = next((b for b in blocks if b.get("type") == "heading"), None)
    title = heading_text(title_heading.get("content")) if title_heading else filename
    block_counts = count_blocks(blocks)

    # Stage 7 -- the normalized artifact (in memory; caller persists it).
    return {
        "schema": SCHEMA,
        "validation": validation["checks"],
        "metadata": {
            "document_name": os.path.splitext(filename)[0],
            "original_filename": filename,
            "format": format_,
            "content_hash_sha256": content_hash,
            "size_bytes": len(data),
            "title": title,
            "parser_version": PARSER_VERSION,
            "pipeline_version": PIPELINE_VERSION,
            "validation_version": VALIDATION_VERSION,
            "chunker": {
                "strategy": "hierarchical_small_to_big_v1",
                "version": HIERARCHICAL_CHUNKER_VERSION,
                "max_tokens": chunk_config["max_tokens"],
                "overlap_tokens": chunk_config["overlap_tokens"],
                "levels": ["document", "section", "leaf"],
            },
            "page_count": validation.get("page_count"),
            "pdf_type": validation.get("pdf_type"),
            "parsed_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "status": "NORMALIZED",
        },
        "structure": {
            "heading_hierarchy": build_heading_hierarchy(blocks),
            "reading_sequence": seq,
            "boilerplate_summary": {
                **boilerplate_summary,
                "excluded_from_chunks": excluded_from_chunks,
            },
        },
        "content": {
            "blocks": [
                {k: v for k, v in b.items() if k not in ("_seq", "_boilerplate")}
                for b in blocks
            ],
            "notes": notes,
            "assets": assets,
            "block_counts": block_counts,
            "plain_text_length": plain_text_length,
        },
        "chunks": chunks,
        "version_diff": version_diff,
    }


def parse_file(file_path, out_dir, previous_file=None):
    with open(file_path, "rb") as fh:
        data = fh.read()
    content_hash = sha256(data)
    filename = os.path.basename(file_path)
    out_name = os.path.splitext(filename)[0] + ".json"
    out_path = os.path.join(out_dir, out_name)
    os.makedirs(out_dir, exist_ok=True)

    previous_artifact = None
    if previous_file:
        with open(previous_file, "r", encoding="utf-8") as fh:
            previous_artifact = json.load(fh)

    def write_artifact(payload):
        with open(out_path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, ensure_ascii=False)
            fh.write("\n")

    def summarize(extra):
        print(json.dumps({"file": filename, **extra}, ensure_ascii=False), flush=True)

    def fail_artifact(code, reason, checks):
        payload = {
            "schema": SCHEMA,
            "validation": checks,
            "metadata": {
                "document_name": os.path.splitext(filename)[0],
                "original_filename": filename,
                "format": "unknown",
                "content_hash_sha256": content_hash,
                "size_bytes": len(data),
                "parser_version": PARSER_VERSION,
                "pipeline_version": PIPELINE_VERSION,
                "validation_version": VALIDATION_VERSION,
                "parsed_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                "status": "FAILED",
            },
            "structure": None,
            "content": None,
            "chunks": [],
            "version_diff": None,
        }
        write_artifact(payload)
        summarize(
            {
                "format": "unknown",
                "sha256": content_hash[:12],
                "status": "FAILED",
                "validation_code": code,
                "reason": reason,
            }
        )

    try:
        normalized = build_normalized(
            data,
            filename=filename,
            file_path=file_path,
            previous_artifact=previous_artifact,
        )
    except IngestionFailed as exc:
        # Persist a FAILED artifact so the failure stays observable, then re-raise.
        fail_artifact(exc.code, exc.reason, exc.checks)
        raise

    write_artifact(normalized)
    meta = normalized["metadata"]
    summarize(
        {
            "format": meta["format"],
            "sha256": meta["content_hash_sha256"][:12],
            "title": meta["title"],
            "blocks": normalized["content"]["block_counts"],
            "plain_text_length": normalized["content"]["plain_text_length"],
            "chunks": len(normalized["chunks"]),
            "embeddable_chunks": len([c for c in normalized["chunks"] if c.get("embeddable")]),
            "boilerplate_excluded": normalized["structure"]["boilerplate_summary"]["excluded_from_chunks"],
            "document_model": meta["format"] not in ("md", "pdf"),
            "version_diff": (normalized["version_diff"] or {}).get("stats"),
            "status": "NORMALIZED",
        }
    )
    return normalized


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="parse.py",
        description=(
            "Ingestion pipeline: validate -> parse -> normalize -> chunk -> diff -> persist "
            "(normalized_document_v2)."
        ),
    )
    parser.add_argument("file", help="source document to ingest")
    parser.add_argument("out_dir", help="directory for the normalized artifact")
    parser.add_argument(
        "--previous",
        metavar="PREVIOUS_JSON",
        help="previous normalized artifact to version-diff chunk hashes against",
    )
    args = parser.parse_args(argv)
    try:
        parse_file(args.file, args.out_dir, args.previous)
    except IngestionFailed:
        return 1
    except KeyboardInterrupt:
        return 130
    except Exception as exc:  # noqa: BLE001 - CLI entry: report and exit non-zero
        print(f"parse failed for {args.file}: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
