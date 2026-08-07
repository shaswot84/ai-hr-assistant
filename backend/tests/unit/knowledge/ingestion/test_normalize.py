"""Ported tests for Unicode normalization, plain-text extraction, and
boilerplate detection (ingestion engine).

Kept 1:1 with ``ingestion_pipeline/tests/test_normalize.py``.
"""

from app.knowledge.ingestion.normalize import (
    block_plain_text,
    collapse_whitespace,
    detect_boilerplate,
    inline_plain_text,
    normalize_unicode,
    token_count,
)


def para(text):
    return {"type": "paragraph", "content": [{"type": "text", "text": text}]}


# --- Unicode & formatting normalization ------------------------------------

def test_glyph_map():
    assert normalize_unicode("\u201cHi\u201d \u2014 ok\u2026") == '"Hi" - ok...'
    assert normalize_unicode("a\u00a0b\u00a0c") == "a b c"
    assert normalize_unicode("\u2022 item") == "* item"
    assert normalize_unicode("\u00a9 2026") == "(c) 2026"
    assert normalize_unicode("\ufeff") == ""


def test_nfkc_composition():
    assert normalize_unicode("caf\u00e9") == "caf\u00e9"
    assert normalize_unicode("\u0065\u0301") == "\u00e9"  # e + combining acute -> é
    assert normalize_unicode("\ufb01ne") == "fine"  # ligature fi -> fi


def test_normalize_preserves_none():
    assert normalize_unicode(None) is None


def test_collapse_whitespace():
    assert collapse_whitespace("  a\t b \n\n c  ") == "a b c"
    assert collapse_whitespace(None) == ""
    assert collapse_whitespace("") == ""


def test_token_count():
    assert token_count("") == 0
    assert token_count(None) == 0
    assert token_count("hello world") == 2
    assert token_count("a, b. c!") == 4  # 3 words + 1 for 3 punctuation marks


# --- Plain-text extraction --------------------------------------------------

def test_inline_plain_text():
    # Text inlines carry their own spacing (anydoc/markdown preserve it);
    # inline_plain_text joins them without inserting separators.
    inlines = [
        {"type": "text", "text": "a "},
        {"type": "link", "content": [{"type": "text", "text": "b"}]},
        {"type": "line_break"},
        {"type": "image", "alt": "c"},
    ]
    assert inline_plain_text(inlines) == "a b c"


def test_block_plain_text_list_table_quote_code():
    lst = {"type": "list", "marker": "bullet", "items": [
        {"blocks": [para("one")]},
        {"blocks": [para("two")]},
    ]}
    assert block_plain_text(lst) == "one two"

    table = {"type": "table", "grid": [
        [{"kind": "origin", "cell": {"blocks": [para("h1")]}},
         {"kind": "origin", "cell": {"blocks": [para("h2")]}}],
        [{"kind": "origin", "cell": {"blocks": [para("d1")]}},
         {"kind": "origin", "cell": {"blocks": [para("d2")]}}],
    ]}
    assert "h1 | h2" in block_plain_text(table)
    assert "d1 | d2" in block_plain_text(table)

    quote = {"type": "block_quote", "blocks": [para("q")]}
    assert block_plain_text(quote) == "q"

    code = {"type": "code_block", "text": "print(1)"}
    assert block_plain_text(code) == "print(1)"


# --- Boilerplate / duplicate detection --------------------------------------

def _blocks(strings):
    return [para(s) for s in strings]


def test_page_number_flagged():
    flags = detect_boilerplate(_blocks(["Page 1", "Page 2", "Body"]))
    assert flags[0]["kind"] == "page_number"
    assert flags[1]["kind"] == "page_number"
    assert flags[2] is None


def test_page_number_of_flagged():
    flags = detect_boilerplate(_blocks(["Page 7 of 12", "Body"]))
    assert flags[0]["kind"] == "page_number"


def test_repeated_bare_digit():
    flags = detect_boilerplate(_blocks(["7", "7", "7", "text"]))
    assert flags[0]["kind"] == "page_number"
    assert flags[0]["count"] == 3
    assert flags[3] is None


def test_single_bare_digit_not_flagged():
    flags = detect_boilerplate(_blocks(["7", "text"]))
    assert flags[0] is None


def test_repeated_header_with_page_tokens():
    blocks = _blocks(["ACME | Page 1", "ACME | Page 2", "ACME | Page 3", "Body"])
    flags = detect_boilerplate(blocks)
    assert flags[0]["kind"] == "repeated"
    assert flags[0]["count"] == 3
    assert flags[1]["kind"] == "repeated"
    assert flags[2]["kind"] == "repeated"
    assert flags[3] is None


def test_exact_duplicates_keep_first():
    blocks = _blocks(["Repeat", "Body", "Repeat"])
    flags = detect_boilerplate(blocks)
    assert flags[0] is None
    assert flags[1] is None
    assert flags[2]["kind"] == "duplicate"
    assert flags[2]["first_index"] == 0


def test_short_text_never_flagged():
    flags = detect_boilerplate(_blocks(["ab", "ab", "ab"]))
    assert all(f is None for f in flags)


def _heading(text, level=2):
    return {"type": "heading", "level": level, "content": [{"type": "text", "text": text}]}


def test_repeated_headings_never_flagged():
    # "Key Points" under every section is structure, not a repeated footer.
    flags = detect_boilerplate([_heading("Key Points"), _heading("Key Points"), _heading("Key Points")])
    assert all(f is None for f in flags)


def test_duplicate_headings_keep_all():
    # Same heading text under different parents must survive chunking.
    blocks = [_heading("Eligibility"), para("a"), _heading("Eligibility"), para("b")]
    flags = detect_boilerplate(blocks)
    assert all(f is None for f in flags)


def test_repeated_paragraphs_still_flagged():
    # Control: identical text as paragraphs IS still a repeated footer.
    flags = detect_boilerplate(_blocks(["Footer", "Footer", "Footer", "Body"]))
    assert flags[0]["kind"] == "repeated"
    assert flags[3] is None


def test_heading_looking_like_page_number_still_flagged():
    # The exemption only covers repeated/duplicate: a heading that is itself
    # a page number is still boilerplate.
    flags = detect_boilerplate([_heading("Page 7")])
    assert flags[0]["kind"] == "page_number"
