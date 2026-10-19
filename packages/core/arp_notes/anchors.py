"""Heading anchors. The UI mirrors this byte-for-byte. Owner: C1a (ga-mxal.25).

`note_links.anchor` is a heading slug or '^block-id' (ADR A.1). The slug is GitHub-style: the
rules below are the contract, and `packages/core/tests/data/anchor_slugs.json` is the shared test
table the UI package mirrors.
"""

from __future__ import annotations

import unicodedata

# Unicode general categories that survive: letters, marks, numbers and connector punctuation
# (so '_' stays). A hyphen and a space are kept explicitly; every other character is dropped.
_KEEP_CATEGORIES = ("L", "M", "N")


def _kept(ch: str) -> bool:
    if ch in "- ":
        return True
    category = unicodedata.category(ch)
    return category.startswith(_KEEP_CATEGORIES) or category == "Pc"


def slug(heading: str) -> str:
    """Return the anchor for a heading's text, or a '^block-id' unchanged.

    `heading` is the heading text without its '#' markers. Rules, in order:
    1. A value that starts with '^' is a block id and passes through untouched.
    2. Trim surrounding whitespace.
    3. Lower-case it.
    4. Drop every character except letters, marks, numbers, '_' (connector punctuation), '-' and
       spaces. Punctuation, symbols and emoji go.
    5. Turn each space into '-'. Runs are not collapsed ('a  b' -> 'a--b'), as on GitHub.
    """
    if heading.startswith("^"):
        return heading
    text = heading.strip().lower()
    return "".join("-" if ch == " " else ch for ch in text if _kept(ch))
