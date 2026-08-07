"""Text normalization helpers for the ingestion pipeline.

Covers two of the pipeline's concerns:
 - Unicode & formatting normalization (challenge #12): NFKC + glyph fixes
   for bullets, smart quotes, em/en dashes, non-breaking spaces, ellipses,
   invisible codepoints, etc.
 - Boilerplate & duplicate-content detection (challenges #5, #6, #8):
   headers/footers that repeat on every page, standalone page numbers,
   and repeated content that would otherwise produce redundant embeddings.

Plain-text extraction (``inline_plain_text`` / ``block_plain_text``) operates
on the *normalized JSON block shape* produced by ``parse.py`` (dicts with a
``type`` key), so the chunker and boilerplate detector can share it without
depending on anydoc.
"""

import math
import re
import unicodedata

# ---------------------------------------------------------------------------
# Unicode & formatting normalization
# ---------------------------------------------------------------------------

GLYPH_MAP = {
    # Curly/smart quotes -> straight
    "\u2018": "'", "\u2019": "'", "\u201A": "'", "\u201B": "'",
    "\u201C": '"', "\u201D": '"', "\u201E": '"', "\u201F": '"',
    # Dashes -> hyphen
    "\u2013": "-", "\u2014": "-",
    # Non-breaking / narrow no-break / figure spaces -> regular space
    "\u00A0": " ", "\u2007": " ", "\u202F": " ",
    # Ellipsis
    "\u2026": "...",
    # Bullet / list markers -> markdown-ish equivalents
    "\u2022": "*", "\u25CF": "*", "\u25E6": "-", "\u2043": "-", "\u00B7": "-",
    # Angle quotes
    "\u00BB": ">>", "\u00AB": "<<",
    # Invisible / zero-width codepoints and BOM
    "\u200B": "", "\u200E": "", "\u200F": "", "\uFEFF": "",
    # Symbols
    "\u00A9": "(c)", "\u00AE": "(r)", "\u2122": "(tm)",
}


def normalize_unicode(s):
    """Normalize a string: map glyphs, then NFKC-compose. Preserves None."""
    if not s:
        return s
    out = "".join(GLYPH_MAP.get(ch, ch) for ch in str(s))
    return unicodedata.normalize("NFKC", out)


def collapse_whitespace(s):
    """Collapse runs of whitespace to a single space and trim."""
    return re.sub(r"\s+", " ", str(s or "")).strip()


def token_count(text):
    """Approximate token count: words plus a share of punctuation.

    Good enough for chunk-budget accounting and token_count metadata; not a
    real tokenizer.
    """
    if not text:
        return 0
    s = str(text)
    words = len(s.split())
    punctuation = len(
        re.findall(r"""[.,;:!?()\[\]{}'"`/|\\=+\-*&%$#@~^<>]""", s)
    )
    return max(1, words + math.ceil(punctuation / 4))


# ---------------------------------------------------------------------------
# Plain-text extraction from the normalized JSON block shape
# ---------------------------------------------------------------------------

def inline_plain_text(inlines):
    parts = []
    for i in inlines or []:
        t = i.get("type")
        if t == "text":
            parts.append(i.get("text", ""))
        elif t == "link":
            parts.append(inline_plain_text(i.get("content")))
        elif t == "image":
            parts.append(i.get("alt") or "")
        elif t == "line_break":
            parts.append(" ")
    return re.sub(r"\s+", " ", "".join(parts)).strip()


def block_plain_text(block):
    if not block:
        return ""
    t = block.get("type")
    if t in ("heading", "paragraph"):
        return inline_plain_text(block.get("content"))
    if t == "list":
        return " ".join(
            " ".join(block_plain_text(b) for b in item.get("blocks", []))
            for item in block.get("items", [])
        )
    if t == "table":
        return "\n".join(
            " | ".join(
                " ".join(block_plain_text(b) for b in slot["cell"].get("blocks", []))
                for slot in row
                if slot.get("kind") == "origin"
            )
            for row in block.get("grid", [])
        )
    if t == "block_quote":
        return " ".join(block_plain_text(b) for b in block.get("blocks", []))
    if t == "code_block":
        return block.get("text") or ""
    return ""


# ---------------------------------------------------------------------------
# Deep normalization of the normalized JSON block shape (text fields)
# ---------------------------------------------------------------------------

def normalize_inline(i):
    if not i:
        return i
    t = i.get("type")
    if t == "text":
        return {**i, "text": normalize_unicode(i.get("text"))}
    if t == "link":
        return {**i, "content": [normalize_inline(x) for x in i.get("content", [])]}
    if t == "image":
        return {**i, "alt": normalize_unicode(i.get("alt") or "")}
    return i


def normalize_blocks(blocks):
    out = []
    for b in blocks or []:
        t = b.get("type")
        if t in ("heading", "paragraph"):
            out.append({**b, "content": [normalize_inline(x) for x in b.get("content", [])]})
        elif t == "list":
            out.append({
                **b,
                "items": [
                    {**it, "blocks": normalize_blocks(it.get("blocks"))}
                    for it in b.get("items", [])
                ],
            })
        elif t == "table":
            out.append({
                **b,
                "grid": [
                    [
                        {**s, "cell": {**s["cell"], "blocks": normalize_blocks(s["cell"].get("blocks"))}}
                        if s.get("kind") == "origin"
                        else s
                        for s in row
                    ]
                    for row in b.get("grid", [])
                ],
            })
        elif t == "block_quote":
            out.append({**b, "blocks": normalize_blocks(b.get("blocks"))})
        else:
            out.append(b)
    return out


# ---------------------------------------------------------------------------
# Boilerplate & duplicate-content detection
# ---------------------------------------------------------------------------

# "Page N" / "Page 7 of 12" -> always a footer.
PAGE_PREFIX_RE = re.compile(r"^page\s*\d{1,4}(\s+of\s+\d+)?\s*$", re.IGNORECASE)
# Bare short number ("7") -> only a footer when it repeats across pages.
BARE_DIGIT_RE = re.compile(r"^\d{1,4}$")
# Combined, exported for reference/tests.
PAGE_NUMBER_RE = re.compile(
    PAGE_PREFIX_RE.pattern + "|" + BARE_DIGIT_RE.pattern, re.IGNORECASE
)
# "Page N" tokens inside longer header/footer lines.
PAGE_TOKEN_RE = re.compile(r"\bpage\s*\d+(\s*of\s*\d+)?\b", re.IGNORECASE)


def strip_page_tokens(t):
    """Text with page-number tokens removed (for header/footer matching)."""
    return re.sub(r"\s+", " ", PAGE_TOKEN_RE.sub(" ", str(t))).strip()


def detect_boilerplate(blocks, min_repeats=3, min_text_length=3):
    """Classify every top-level block as boilerplate, duplicate, or normal.

    Returns a list aligned with ``blocks``; entries are ``None`` for normal
    blocks, otherwise a dict:

        {boilerplate: True, kind: 'page_number'|'repeated'|'duplicate',
         count, first_index?, text}

     - ``page_number``: standalone page-number-like text (always excluded),
       including blocks made up only of page tokens ("Page 1 Page 2").
     - ``repeated``: the identical normalized text appears >= min_repeats
       times (headers/footers, confidentiality notices) -- all occurrences
       excluded. Page-bearing header/footer lines whose only difference is
       the page number ("ABC Company | HR Policy | Page 6") match after
       page-token stripping.
     - ``duplicate``: the text appears 2..min_repeats-1 times -- the *first*
       occurrence is kept, later ones flagged and excluded from chunking.

    Heading blocks are exempt from ``repeated``/``duplicate`` classification:
    a heading name that recurs across sections ("Key Points", "Eligibility")
    is a real section boundary, not a footer. Page-number classification
    (``page_number``) still applies to every block.
    """
    out = [None] * len(blocks)
    texts = [collapse_whitespace(normalize_unicode(block_plain_text(b))) for b in blocks]
    # Block type decides what repeated/duplicate detection may flag: headings
    # are structure, never header/footer boilerplate, even when their text
    # repeats across sections ("Key Points", "Eligibility", "Procedure").
    types = [(b or {}).get("type") for b in blocks]

    freq = {}
    page_freq = {}
    digit_freq = {}
    page_keys = []
    for t in texts:
        if BARE_DIGIT_RE.match(t):
            digit_freq[t] = digit_freq.get(t, 0) + 1
            page_keys.append(None)
            continue
        if len(t) < min_text_length:
            page_keys.append(None)
            continue
        freq[t] = freq.get(t, 0) + 1
        k = strip_page_tokens(t)
        if k != t and len(k) >= min_text_length:
            page_freq[k] = page_freq.get(k, 0) + 1
            page_keys.append(k)
        else:
            page_keys.append(None)

    for i, t in enumerate(texts):
        if PAGE_PREFIX_RE.match(t):
            out[i] = {"boilerplate": True, "kind": "page_number", "count": 1, "text": t}
        elif BARE_DIGIT_RE.match(t) and digit_freq.get(t, 0) >= 2:
            out[i] = {"boilerplate": True, "kind": "page_number", "count": digit_freq[t], "text": t}
        elif len(t) >= 3 and strip_page_tokens(t) == "" and PAGE_TOKEN_RE.search(t):
            # Made up only of page tokens (merged into one paragraph by
            # markdown recovery) -- a page-number footer.
            out[i] = {"boilerplate": True, "kind": "page_number", "count": 1, "text": t}

    first_index = {}
    for i, t in enumerate(texts):
        if out[i] or len(t) < min_text_length:
            continue
        # Headings stay structural: a repeated heading name is a real section
        # boundary, not a footer. Page-number flags above still apply.
        if types[i] == "heading":
            continue
        n = freq.get(t, 0)
        pk = page_keys[i]
        pn = page_freq.get(pk, 0) if pk else 0
        if pn >= min_repeats:
            out[i] = {
                "boilerplate": True,
                "kind": "repeated",
                "count": pn,
                "text": t,
                "page_stripped": pk,
            }
        elif n >= min_repeats:
            out[i] = {"boilerplate": True, "kind": "repeated", "count": n, "text": t}
        elif n > 1:
            if t in first_index:
                out[i] = {
                    "boilerplate": True,
                    "kind": "duplicate",
                    "count": n,
                    "first_index": first_index[t],
                    "text": t,
                }
            else:
                first_index[t] = i

    return out
