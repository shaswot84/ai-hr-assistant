"""Citation marker parsing and rewriting (``[N]``, ``[2, 3]``, ``[1-5]``).

The generation prompt requires the LLM to end every claim with bracketed
``[N]`` markers that reference the numbered evidence blocks. These helpers
validate and rewrite those markers so they always index exactly the citation
set being served — dense ``1..k`` — and drop any number the LLM invented
(out of range, comma/range forms included).
"""

import re

_MARKER_GROUP = re.compile(r"\[([0-9,\s\u2013\u2014-]+)\]")
_NUMBER = re.compile(r"\d{1,3}")
_RANGE_SEP = re.compile(r"[\u2013\u2014-]")
_TOKEN_SEP = re.compile(r"[\s,]+")


def _numbers_in(group: str) -> set[int]:
    """Expand a marker group's inner text into the set of chunk indexes.

    Handles commas and ranges: "1, 4-6" -> {1, 4, 5, 6}.
    """
    numbers: set[int] = set()
    for token in _TOKEN_SEP.split(group.strip()):
        if not token:
            continue
        parts = _RANGE_SEP.split(token)
        if len(parts) == 1:
            if parts[0].isdigit():
                numbers.add(int(parts[0]))
            continue
        start_s, end_s = parts[0], parts[-1]
        if start_s.isdigit() and end_s.isdigit():
            start, end = int(start_s), int(end_s)
            numbers.update(range(min(start, end), max(start, end) + 1))
    return numbers


def _format_group(numbers: set[int]) -> str:
    """Render indexes back as a compact bracket group, ranges collapsed.

    {1, 2, 3, 5} -> "[1-3, 5]".
    """
    nums = sorted(numbers)
    if not nums:
        return ""
    ranges: list[str] = []
    start = prev = nums[0]
    for cur in nums[1:]:
        if cur == prev + 1:
            prev = cur
            continue
        ranges.append(f"{start}" if start == prev else f"{start}-{prev}")
        start = prev = cur
    ranges.append(f"{start}" if start == prev else f"{start}-{prev}")
    return "[" + ", ".join(ranges) + "]"


def parse_marker_set(text: str) -> set[int]:
    """All chunk indexes referenced by markers anywhere in the text."""
    found: set[int] = set()
    for match in _MARKER_GROUP.finditer(text):
        found.update(_numbers_in(match.group(1)))
    return found


def renumber_markers(text: str, keep_indices: list[int]) -> str:
    """Rewrite markers so they index the kept citations densely 1..k.

    ``keep_indices`` must be a sorted list of 1-based original citation
    indexes to keep. Every referenced number not in ``keep_indices`` is
    dropped; a marker group left with no numbers is removed entirely.

    Because the dense mapping is monotonic, any range (``[1] - [5]``) stays a
    valid range of the served set, e.g. keep ``[1, 2, 5]`` turns ``[1, 5]``
    into ``[1, 3]``.
    """
    mapping = {idx: pos for pos, idx in enumerate(keep_indices, start=1)}

    def _replace(match: re.Match[str]) -> str:
        dense = {mapping[n] for n in _numbers_in(match.group(1)) if n in mapping}
        return _format_group(dense)

    return _MARKER_GROUP.sub(_replace, text)


def strip_invalid_markers(text: str, citation_count: int) -> str:
    """Remove markers referencing sources never retrieved (identity renumber)."""
    return renumber_markers(text, list(range(1, citation_count + 1)))
