"""Ported tests for Markdown structure recovery (ingestion engine).

Kept 1:1 with ``ingestion_pipeline/tests/test_markdown.py``.
"""

from app.knowledge.ingestion.normalize import block_plain_text
from app.knowledge.ingestion.parse import parse_inlines, parse_markdown


def test_atx_headings_and_paragraph():
    blocks = parse_markdown("# Title\n\nSome **bold** text.\n")
    assert [b["type"] for b in blocks] == ["heading", "paragraph"]
    assert blocks[0]["level"] == 1
    assert blocks[0]["content"][0]["text"] == "Title"
    p = blocks[1]["content"]
    assert p[0] == {"type": "text", "text": "Some "}
    assert p[1] == {"type": "text", "text": "bold", "style": {"bold": True}}
    assert p[2] == {"type": "text", "text": " text."}


def test_setext_headings():
    blocks = parse_markdown("Doc title\n========\n\nBody\n---\n")
    assert [b["type"] for b in blocks] == ["heading", "heading"]
    assert blocks[0]["level"] == 1
    assert blocks[0]["content"][0]["text"] == "Doc title"
    assert blocks[1]["level"] == 2
    assert blocks[1]["content"][0]["text"] == "Body"


def test_inline_emphasis_code_and_links():
    blocks = parse_markdown("a *it* b `code` c [link](https://x.dev) d\n")
    p = blocks[0]["content"]
    assert p[0] == {"type": "text", "text": "a "}
    assert p[1] == {"type": "text", "text": "it", "style": {"italic": True}}
    assert p[2] == {"type": "text", "text": " b "}
    assert p[3] == {"type": "text", "text": "code", "style": {"code": True}}
    assert p[4] == {"type": "text", "text": " c "}
    assert p[5]["type"] == "link"
    assert p[5]["target"] == {"kind": "external", "value": "https://x.dev"}
    assert p[5]["content"] == [{"type": "text", "text": "link"}]
    assert p[6] == {"type": "text", "text": " d"}


def test_relative_and_anchor_links():
    blocks = parse_markdown("[rel](/docs/x) and [anch](#sec-1)\n")
    p = blocks[0]["content"]
    assert p[0]["target"]["kind"] == "relative"
    assert p[2]["target"]["kind"] == "anchor"


def test_mid_word_underscore_is_literal():
    blocks = parse_markdown("foo_bar baz_qux\n")
    assert blocks[0]["content"] == [{"type": "text", "text": "foo_bar baz_qux"}]


def test_bold_containing_italic():
    blocks = parse_markdown("**a *b* c**\n")
    styles = [i["style"] for i in blocks[0]["content"] if i.get("type") == "text"]
    assert {"bold": True} in styles
    assert {"bold": True, "italic": True} in styles


def test_strike_and_image():
    blocks = parse_markdown("~~gone~~ ![alt](img.png)\n")
    p = blocks[0]["content"]
    assert p[0] == {"type": "text", "text": "gone", "style": {"strike": True}}
    assert p[1] == {"type": "text", "text": " "}
    assert p[2]["type"] == "image"
    assert p[2]["alt"] == "alt"
    assert p[2]["source"] == {"kind": "relative", "url": "img.png"}


def test_escaped_markup():
    blocks = parse_markdown(r"\*not italic\*" + "\n")
    text = "".join(i["text"] for i in blocks[0]["content"])
    assert text == r"\*not italic\*"


def test_pipe_table():
    md = "| Name | Age |\n|---|---|\n| A | 1 |\n| B | 2 |\n"
    blocks = parse_markdown(md)
    assert len(blocks) == 1
    t = blocks[0]
    assert t["type"] == "table"
    assert t["header_rows"] == 1
    assert len(t["grid"]) == 3  # header + 2 data rows
    assert t["grid"][0][0]["cell"]["blocks"][0]["content"][0]["text"] == "Name"
    assert t["grid"][2][1]["cell"]["blocks"][0]["content"][0]["text"] == "2"


def test_table_cells_parse_inlines():
    blocks = parse_markdown("| **H** | x |\n|---|---|\n")
    t = blocks[0]
    cell = t["grid"][0][0]["cell"]["blocks"][0]["content"][0]
    assert cell["style"] == {"bold": True}


def test_bullet_list():
    blocks = parse_markdown("- one\n- two\n")
    b = blocks[0]
    assert b["type"] == "list"
    assert b["marker"] == "bullet"
    assert b["start"] == 1
    assert len(b["items"]) == 2
    assert b["items"][0]["blocks"][0]["content"][0]["text"] == "one"


def test_ordered_list_start():
    blocks = parse_markdown("3. three\n4. four\n")
    b = blocks[0]
    assert b["marker"] == "ordered"
    assert b["start"] == 3
    assert len(b["items"]) == 2


def test_task_list():
    blocks = parse_markdown("- [x] done\n- [ ] todo\n")
    b = blocks[0]
    assert b["items"][0]["checked"] is True
    assert b["items"][1]["checked"] is False


def test_nested_list():
    md = "- a\n  - a1\n  - a2\n- b\n"
    blocks = parse_markdown(md)
    b = blocks[0]
    assert len(b["items"]) == 2
    child = b["items"][0]["blocks"][1]
    assert child["type"] == "list"
    assert [it["blocks"][0]["content"][0]["text"] for it in child["items"]] == ["a1", "a2"]


def test_nested_list_returns_to_sibling():
    md = "- a\n  - a1\n- b\n"
    blocks = parse_markdown(md)
    b = blocks[0]
    assert len(b["items"]) == 2
    assert b["items"][1]["blocks"][0]["content"][0]["text"] == "b"


def test_blockquote():
    blocks = parse_markdown("> quoted line\n> second line\n")
    b = blocks[0]
    assert b["type"] == "block_quote"
    inner = b["blocks"][0]
    assert inner["type"] == "paragraph"
    assert inner["content"][0]["text"] == "quoted line second line"


def test_blockquote_lazy_continuation():
    blocks = parse_markdown("> first\nlazy\n")
    b = blocks[0]
    assert b["type"] == "block_quote"
    assert b["blocks"][0]["content"][0]["text"] == "first lazy"


def test_blockquote_ends_on_blank():
    blocks = parse_markdown("> a\n\nb\n")
    assert blocks[0]["type"] == "block_quote"
    assert blocks[1]["type"] == "paragraph"
    assert blocks[1]["content"][0]["text"] == "b"


def test_nested_blockquote():
    blocks = parse_markdown("> outer\n> > inner\n")
    b = blocks[0]
    assert b["type"] == "block_quote"
    inner = b["blocks"][1]
    assert inner["type"] == "block_quote"


def test_fenced_code_with_lang():
    blocks = parse_markdown("```py\nprint(1)\n```\n")
    b = blocks[0]
    assert b["type"] == "code_block"
    assert b["lang"] == "py"
    assert b["text"].strip() == "print(1)"


def test_fenced_code_literal_markup():
    blocks = parse_markdown("```\n# not a heading\n```\n")
    b = blocks[0]
    assert b["type"] == "code_block"
    assert b["text"].strip() == "# not a heading"


def test_thematic_break():
    blocks = parse_markdown("a\n\n---\n\nb\n")
    assert [b["type"] for b in blocks] == ["paragraph", "rule", "paragraph"]


def test_paragraph_merges_lines():
    blocks = parse_markdown("line one\nline two\n")
    assert blocks[0]["content"][0]["text"] == "line one line two"


def test_list_paragraph_continuation():
    blocks = parse_markdown("- item\n  continued here\n")
    b = blocks[0]
    assert block_plain_text(b) == "item continued here"


def test_list_ends_after_blank_line():
    blocks = parse_markdown("- item\n\nparagraph\n")
    assert blocks[0]["type"] == "list"
    assert blocks[1]["type"] == "paragraph"
    assert blocks[1]["content"][0]["text"] == "paragraph"


def test_heading_hierarchy_and_order():
    md = "# A\n\n## B\n\n## C\n\n### D\n"
    blocks = parse_markdown(md)
    assert [b["level"] for b in blocks] == [1, 2, 2, 3]
    assert [b["content"][0]["text"] for b in blocks] == ["A", "B", "C", "D"]


def test_parse_inlines_direct():
    assert parse_inlines("plain") == [{"type": "text", "text": "plain"}]
    assert parse_inlines("") == []
