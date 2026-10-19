"""anchors.slug against the shared table the UI mirrors (tests/data/anchor_slugs.json)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from arp_notes.anchors import slug

TABLE = json.loads((Path(__file__).parent / "data" / "anchor_slugs.json").read_text("utf-8"))


@pytest.mark.parametrize("case", TABLE, ids=[c["heading"] or "<empty>" for c in TABLE])
def test_slug_table(case: dict[str, str]) -> None:
    assert slug(case["heading"]) == case["slug"]


def test_slug_is_idempotent_for_plain_slugs() -> None:
    for case in TABLE:
        assert slug(case["slug"]) == case["slug"]
