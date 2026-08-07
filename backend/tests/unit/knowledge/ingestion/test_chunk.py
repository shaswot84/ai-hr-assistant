"""Ported tests for the structure-aware chunker (ingestion engine).

Kept 1:1 with ``ingestion_pipeline/tests/test_chunk.py``.
"""

from app.knowledge.ingestion.chunk import chunk_blocks, hierarchical_chunk


def para(text):
    return {"type": "paragraph", "content": [{"type": "text", "text": text}]}


def heading(text, level=1):
    return {"type": "heading", "level": level, "content": [{"type": "text", "text": text}]}


def flag(block):
    block["_boilerplate"] = True
    return block


def test_single_chunk_under_budget():
    chunks = chunk_blocks([para("hello world")], max_tokens=500, overlap_tokens=50)
    assert len(chunks) == 1
    c = chunks[0]
    assert c["chunk_index"] == 0
    assert c["section_path"] == []
    assert c["parent_section"] is None
    assert c["page_number"] is None
    assert c["source_blocks"] == [0, 0]
    assert c["overlap_from_previous"] is None
    assert "content_hash_sha256" in c
    assert c["processed_content"] == c["content"]


def test_size_split_carries_overlap():
    words = "word " * 60  # ~60 tokens
    blocks = [para(words), para(words), para(words)]
    chunks = chunk_blocks(blocks, max_tokens=100, overlap_tokens=10)
    assert len(chunks) >= 2
    for c in chunks[1:]:
        assert c["overlap_from_previous"]
        assert c["processed_content"].startswith(c["overlap_from_previous"])
        assert c["content"] != c["processed_content"]


def test_headings_merge_under_budget():
    blocks = [
        heading("Intro"),
        para("alpha beta gamma delta"),
        heading("Details", level=2),
        para("epsilon zeta eta theta"),
    ]
    chunks = chunk_blocks(blocks, max_tokens=1000, overlap_tokens=50)
    assert len(chunks) == 1
    assert chunks[0]["section_path"] == ["Intro"]


def test_sections_after_size_splits():
    blocks = [
        heading("One"),
        para("w " * 200),   # oversized -> its own chunk
        heading("Two"),
        para("x"),          # small -> merges into the Two chunk
    ]
    chunks = chunk_blocks(blocks, max_tokens=100, overlap_tokens=50)
    assert [c["section_path"] for c in chunks] == [["One"], ["One"], ["Two"]]
    # A heading opens a fresh chunk without carrying overlap.
    assert chunks[2]["overlap_from_previous"] is None


def test_oversized_block_gets_own_chunk():
    blocks = [para("big " * 500), para("small")]
    chunks = chunk_blocks(blocks, max_tokens=100, overlap_tokens=50)
    assert len(chunks) == 2
    assert chunks[0]["content"].startswith("big")
    assert chunks[1]["content"] == "small"


def test_boilerplate_excluded_from_chunks():
    blocks = [
        heading("A"),
        flag(para("footer")),
        para("real content here"),
    ]
    chunks = chunk_blocks(blocks, max_tokens=500, overlap_tokens=50)
    assert len(chunks) == 1
    assert "footer" not in chunks[0]["content"]
    assert chunks[0]["excluded_boilerplate"] == 1


def test_empty_and_rule_blocks_skipped():
    blocks = [
        {"type": "rule"},
        {"type": "paragraph", "content": []},
        para("real"),
    ]
    chunks = chunk_blocks(blocks, max_tokens=500, overlap_tokens=50)
    assert len(chunks) == 1
    assert chunks[0]["content"] == "real"


def test_blocks_without_seq_get_indexed():
    chunks = chunk_blocks([para("a"), para("b")], max_tokens=500, overlap_tokens=50)
    assert chunks[0]["source_blocks"] == [0, 1]


def test_token_count_includes_overlap():
    words = "word " * 60
    blocks = [para(words), para(words)]
    chunks = chunk_blocks(blocks, max_tokens=100, overlap_tokens=20)
    c = chunks[1]
    base = len(c["content"].split())
    assert c["token_count"] >= base  # upper bound includes overlap tokens


# ---------------------------------------------------------------------------
# Hierarchical (small-to-big) chunker
# ---------------------------------------------------------------------------

def _seq(blocks):
    for i, b in enumerate(blocks):
        b.setdefault("_seq", i)
    return blocks


def test_hierarchy_document_section_leaf():
    blocks = _seq([
        heading("1. Overview", 1),
        para("alpha beta gamma delta"),
        heading("Mission", 2),
        para("we build"),
        heading("2. Policies", 1),
        para("policy one"),
    ])
    rows = hierarchical_chunk(blocks, max_tokens=500, overlap_tokens=50)
    levels = [r["chunk_level"] for r in rows]
    # document root + per-heading sections + leaves
    assert levels[0] == "document"
    assert levels.count("section") >= 2
    # exactly one document row
    assert levels.count("document") == 1
    # leaves are the embeddable rows
    leaves = [r for r in rows if r["embeddable"]]
    assert all(r["chunk_level"] == "leaf" for r in leaves)
    assert leaves, "must have at least one embeddable leaf"


def test_hierarchical_parent_chain_and_ancestors():
    blocks = _seq([
        heading("1. Overview", 1),
        para("alpha beta gamma delta"),
        heading("Mission", 2),
        para("we build"),
    ])
    rows = hierarchical_chunk(blocks, max_tokens=500, overlap_tokens=50)
    by_index = {r["chunk_index"]: r for r in rows}
    # Pick the leaf under "Mission": parent is its section, ancestors chain leaf->section->...->document
    leaf = next(r for r in rows if r["chunk_level"] == "leaf" and r["section_path"])
    assert leaf["parent_chunk_id"] is not None
    parent = by_index[leaf["parent_chunk_id"]]
    assert parent["chunk_level"] == "section"
    # ancestors climb to the document root (chunk_index 0)
    assert leaf["ancestors"][-1] == 0
    assert all(a in by_index for a in leaf["ancestors"])


def test_hierarchical_sections_do_not_embed():
    blocks = _seq([
        heading("A", 1), para("x"),
        heading("B", 1), para("y"),
    ])
    rows = hierarchical_chunk(blocks, max_tokens=500, overlap_tokens=50)
    sections = [r for r in rows if r["chunk_level"] == "section"]
    assert sections
    assert all(r["embeddable"] is False for r in sections)


def test_hierarchical_size_split_carries_overlap():
    blocks = _seq([heading("S", 1)] + [para("word " * 40) for _ in range(4)])
    rows = hierarchical_chunk(blocks, max_tokens=80, overlap_tokens=15)
    leaves = [r for r in rows if r["embeddable"]]
    assert len(leaves) >= 2
    assert any(r.get("overlap_from_previous") for r in leaves)
    assert leaves[0]["parent_chunk_id"] == leaves[1]["parent_chunk_id"]
