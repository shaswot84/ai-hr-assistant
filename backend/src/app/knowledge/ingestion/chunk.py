"""Structure-aware chunker (challenges #7, #10, #11).

Walks top-level blocks in reading order, tracks the live heading stack to
build the section path, and groups blocks into chunks under a token budget
(``INGEST_CHUNK_MAX_TOKENS``, default 500) with configurable overlap
(``INGEST_CHUNK_OVERLAP_TOKENS``, default 50).

Rules:
 - A new heading opens a natural boundary: if the open chunk is already at
   or over budget it is closed *without* overlap when the next block is a
   heading.
 - Splits caused purely by size mid-content carry overlap of the previous
   chunk's trailing text (embedded via ``processed_content``).
 - A single block larger than the budget (e.g. a huge table) gets its own
   chunk and is never split mid-block.
 - Blocks flagged as boilerplate (page numbers, repeated headers/footers,
   later duplicates) are excluded from chunks; only the first occurrence of
   duplicated content is embedded.

Each chunk carries provenance for the ingestion contract: section_path,
parent_section (both pinned to the chunk's opening section; short following
sections merged into the chunk keep the opening section's citation),
page_number (None -- see README), token_count (base tokens plus overlap
tokens, so it is an upper bound on the budget), a content hash
(version-diffing key), and the source reading-sequence range.
``excluded_boilerplate`` is approximate: boilerplate blocks before the first
or after the last chunk are excluded but attributed to no chunk.
"""

import hashlib
import os
import re

from app.knowledge.ingestion.normalize import (
    block_plain_text,
    collapse_whitespace,
    normalize_unicode,
    token_count,
)

CHUNKER_VERSION = "structure_aware_chunker_v1"
HIERARCHICAL_CHUNKER_VERSION = "hierarchical_small_to_big_v1"


def _env_int(name, default):
    try:
        v = int(os.environ.get(name, ""))
    except (TypeError, ValueError):
        return default
    return v if v > 0 else default


config = {
    "max_tokens": _env_int("INGEST_CHUNK_MAX_TOKENS", 500),
    "overlap_tokens": _env_int("INGEST_CHUNK_OVERLAP_TOKENS", 50),
}


def sha256(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def tail_tokens(text, tokens):
    """Last ~``tokens`` words of ``text``, for chunk overlap."""
    words = [w for w in re.split(r"\s+", str(text or "").strip()) if w]
    n = max(0, len(words) - max(0, tokens))
    return " ".join(words[n:])


def chunk_blocks(blocks, max_tokens=None, overlap_tokens=None):
    """Chunk top-level normalized blocks (dicts; may carry ``_seq`` and
    ``_boilerplate`` internal fields set by the caller). Returns a list of
    chunk dicts."""
    if max_tokens is None:
        max_tokens = config["max_tokens"]
    if overlap_tokens is None:
        overlap_tokens = config["overlap_tokens"]

    chunks = []
    heading_stack = []
    current = None
    pending_overlap = None

    def close(next_overlap):
        nonlocal current, pending_overlap
        if not current or len(current["blocks"]) == 0:
            current = None
            return
        text = "\n".join(block_plain_text(b) for b in current["blocks"])
        text = re.sub(r"\n{3,}", "\n\n", text).strip()
        overlap_text = current["overlap_from_previous"] or None
        processed = collapse_whitespace(
            normalize_unicode((overlap_text + " " if overlap_text else "") + text)
        )
        chunks.append(
            {
                "chunk_index": len(chunks),
                "content": text,
                "processed_content": processed,
                "section_path": current["section_path"],
                "parent_section": current["parent_section"],
                "page_number": None,
                "token_count": current["tokens"]
                + (token_count(overlap_text) if overlap_text else 0),
                "char_count": len(text),
                "content_hash_sha256": sha256(processed),
                "source_blocks": [current["first_seq"], current["last_seq"]],
                "excluded_boilerplate": current.get("excluded_boilerplate") or 0,
                "overlap_from_previous": overlap_text,
            }
        )
        current = None
        # The tail of the chunk we just closed becomes the next chunk's overlap.
        pending_overlap = next_overlap or None

    def start_new(seq):
        nonlocal current, pending_overlap
        current = {
            "blocks": [],
            "tokens": 0,
            "first_seq": seq,
            "last_seq": None,
            "section_path": [h["text"] for h in heading_stack],
            "parent_section": heading_stack[-1]["text"] if heading_stack else None,
            "excluded_boilerplate": 0,
            "overlap_from_previous": pending_overlap,
        }
        pending_overlap = None

    for seq, b in enumerate(blocks):
        # Blocks normally carry ``_seq`` from the caller; fall back to the
        # position for direct use of ``chunk_blocks`` (e.g. tests).
        seq = b.get("_seq", seq)

        # Boilerplate: excluded from chunks but still counted for audit.
        if b.get("_boilerplate"):
            if current:
                current["excluded_boilerplate"] += 1
            continue

        text = collapse_whitespace(normalize_unicode(block_plain_text(b)))
        n = token_count(text)
        if n == 0:
            continue  # empty paragraph / rule

        # Maintain the heading stack before deciding chunk placement, so a
        # heading that opens a new section lands with the correct path.
        if b.get("type") == "heading":
            level = b.get("level", 1)
            while heading_stack and heading_stack[-1]["level"] >= level:
                heading_stack.pop()
            heading_stack.append({"level": level, "text": text})

        if current and current["tokens"] + n > max_tokens:
            at_heading = b.get("type") == "heading"
            tail = (
                None
                if at_heading
                else tail_tokens(
                    " ".join(block_plain_text(x) for x in current["blocks"]), overlap_tokens
                )
            )
            close(tail)

        if n > max_tokens:
            # Oversized single block: its own chunk, never split.
            close(None)
            start_new(seq)
            current["blocks"] = [b]
            current["tokens"] = n
            current["last_seq"] = seq
            current["section_path"] = [h["text"] for h in heading_stack]
            current["parent_section"] = heading_stack[-1]["text"] if heading_stack else None
            close(None)
            continue

        if not current:
            start_new(seq)
        current["blocks"].append(b)
        current["tokens"] += n
        current["last_seq"] = seq
        # section_path / parent_section stay pinned to where the chunk starts;
        # headings opened later inside an undersized chunk keep their own
        # boundary but the chunk still cites its opening section.

    close(None)
    return chunks



# ---------------------------------------------------------------------------
# Hierarchical chunking (small-to-big)
# ---------------------------------------------------------------------------
#
# Builds a heading tree from the normalized blocks and emits a tree of chunks:
#
#     document  (1)  whole document -- top context, not embedded
#     section   (n)  one per real heading -- section subtree text, context
#     leaf      (k)  budget-split slices of a section's own blocks -- embedded
#
# Only ``leaf`` rows are embedded + BM25-indexed, so embedding cost scales
# with content, not with hierarchy depth. ``section``/``document`` rows are
# the *bigger context* a query expands into via ``parent_chunk_id`` once a
# leaf matches (small-to-big retrieval). Every row keeps the provenance the
# ingestion contract requires (section_path, parent_section, page_number,
# source_blocks, content_hash_sha256) plus hierarchical links (chunk_level,
# parent_chunk_id, children, ancestors).


def _blocks_text(blks):
    return "\n".join(block_plain_text(b) for b in blks)


def _tree_text(node):
    """Recursive plain text of a section: title + own blocks + child subtrees."""
    parts = []
    if node.get("title"):
        parts.append(node["title"])
    if node.get("blocks"):
        parts.append(_blocks_text(node["blocks"]))
    for c in node.get("children", []):
        t = _tree_text(c)
        if t:
            parts.append(t)
    return "\n\n".join(parts)


def _block_range(blks):
    if not blks:
        return None
    seqs = [b.get("_seq") for b in blks if b.get("_seq") is not None]
    return [min(seqs), max(seqs)] if seqs else None


def _make_leaf(blks, overlap):
    text = "\n".join(block_plain_text(b) for b in blks)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    overlap_text = overlap or None
    processed = collapse_whitespace(
        normalize_unicode((overlap_text + " " if overlap_text else "") + text)
    )
    return {
        "chunk_level": "leaf",
        "content": text,
        "processed_content": processed,
        "page_number": None,
        "token_count": token_count(processed),
        "char_count": len(text),
        "content_hash_sha256": sha256(processed),
        "source_blocks": _block_range(blks),
        "overlap_from_previous": overlap_text,
        "embeddable": True,
        "section_path": None,
        "parent_section": None,
        "parent_chunk_id": None,
        "children": [],
    }


def _split_leaves(blocks, max_tokens, overlap_tokens):
    """Budget-split a flat block list into embeddable leaf rows (with overlap)."""
    leaves = []
    current = []
    cur_tokens = 0
    pending_overlap = None
    for b in blocks:
        text = collapse_whitespace(normalize_unicode(block_plain_text(b)))
        n = token_count(text)
        if n == 0:
            continue
        if current and cur_tokens + n > max_tokens:
            leaves.append(_make_leaf(current, pending_overlap))
            pending_overlap = tail_tokens(
                " ".join(block_plain_text(x) for x in current), overlap_tokens
            )
            current = []
            cur_tokens = 0
        current.append(b)
        cur_tokens += n
    if current:
        leaves.append(_make_leaf(current, pending_overlap))
    return leaves


def hierarchical_chunk(blocks, max_tokens=None, overlap_tokens=None):
    """Small-to-big hierarchical chunking. See module docstring.

    Returns a flat list of rows in DFS order (parent before children);
    ``chunk_index`` is the DFS position (stable across runs for the same
    content), and ``content_hash_sha256`` is the version-diff key.
    """
    if max_tokens is None:
        max_tokens = config["max_tokens"]
    if overlap_tokens is None:
        overlap_tokens = config["overlap_tokens"]

    # 1. Build the heading tree (boilerplate + empty blocks excluded).
    root = {"kind": "document", "level": 0, "title": None,
            "blocks": [], "children": [], "path": []}
    stack = [root]
    for b in blocks:
        if b.get("_boilerplate"):
            continue
        text = collapse_whitespace(normalize_unicode(block_plain_text(b)))
        if token_count(text) == 0:
            continue
        if b.get("type") == "heading":
            level = b.get("level", 1)
            while len(stack) > 1 and stack[-1]["level"] >= level:
                stack.pop()
            node = {
                "kind": "section",
                "level": level,
                "title": text,
                "blocks": [],
                "children": [],
                "path": stack[-1]["path"] + [text],
            }
            stack[-1]["children"].append(node)
            stack.append(node)
        else:
            stack[-1]["blocks"].append(b)

    rows = []

    def add(row):
        row["chunk_index"] = len(rows)
        rows.append(row)
        return row["chunk_index"]

    def emit_section(node, parent_chunk_id, parent_section):
        sec_text = _tree_text(node)
        processed = collapse_whitespace(normalize_unicode(sec_text))
        sec_row = {
            "chunk_index": None,
            "chunk_level": "section",
            "content": sec_text,
            "processed_content": processed,
            "section_path": list(node["path"]),
            "parent_section": parent_section,
            "page_number": None,
            "token_count": token_count(processed),
            "char_count": len(sec_text),
            "content_hash_sha256": sha256(processed),
            "source_blocks": _block_range(node["blocks"]),
            "overlap_from_previous": None,
            "embeddable": False,
            "parent_chunk_id": parent_chunk_id,
            "children": [],
        }
        sec_idx = add(sec_row)
        for leaf in _split_leaves(node["blocks"], max_tokens, overlap_tokens):
            leaf["section_path"] = list(node["path"])
            leaf["parent_section"] = node["title"] or parent_section
            leaf["parent_chunk_id"] = sec_idx
            sec_row["children"].append(add(leaf))
        for child in node["children"]:
            sec_row["children"].append(emit_section(child, sec_idx, node["title"]))
        return sec_idx

    # 2. Document row (whole doc context) + its preamble leaves + sections.
    doc_text = _tree_text(root)
    doc_processed = collapse_whitespace(normalize_unicode(doc_text))
    doc_row = {
        "chunk_index": None,
        "chunk_level": "document",
        "content": doc_text,
        "processed_content": doc_processed,
        "section_path": [],
        "parent_section": None,
        "page_number": None,
        "token_count": token_count(doc_processed),
        "char_count": len(doc_text),
        "content_hash_sha256": sha256(doc_processed),
        "source_blocks": _block_range(root["blocks"]),
        "overlap_from_previous": None,
        "embeddable": False,
        "parent_chunk_id": None,
        "children": [],
    }
    doc_idx = add(doc_row)
    for leaf in _split_leaves(root["blocks"], max_tokens, overlap_tokens):
        leaf["section_path"] = []
        leaf["parent_section"] = None
        leaf["parent_chunk_id"] = doc_idx
        doc_row["children"].append(add(leaf))
    for child in root["children"]:
        doc_row["children"].append(emit_section(child, doc_idx, None))

    # 3. Resolve ancestor chains (walk parent links upward).
    by_index = {r["chunk_index"]: r for r in rows}
    for r in rows:
        ancestors = []
        pid = r["parent_chunk_id"]
        seen = set()
        while pid is not None and pid not in seen:
            seen.add(pid)
            ancestors.append(pid)
            pid = by_index[pid]["parent_chunk_id"]
        r["ancestors"] = ancestors

    return rows
