"""PROTOCOL.md is the initial copy of ADR Appendix A + contract K§1–K§6 (C0)."""

from __future__ import annotations

import re
from pathlib import Path

PROTOCOL = Path(__file__).resolve().parents[3] / "PROTOCOL.md"


def test_protocol_version_is_declared() -> None:
    assert "protocol_version: 1" in PROTOCOL.read_text()


def test_base_contract_and_amendments_are_present() -> None:
    headings = set(re.findall(r"^#{2,3} (A\.\d|K§\d(?:\.\d)?)\b", PROTOCOL.read_text(), re.M))
    assert {f"A.{n}" for n in range(1, 7)} <= headings
    assert {f"K§{n}" for n in range(1, 7)} <= headings


def test_private_fixture_is_not_vendored() -> None:
    assert "howat" not in PROTOCOL.read_text().lower()


def test_k4_copy_carries_the_k12_port_signatures() -> None:
    text = PROTOCOL.read_text()
    assert "Storage.put(user_id, sha256, stream, *, mime, size_bytes) -> str" in text
    assert "reconcile(user_id, spans: Sequence[Span]) -> list[list[Candidate]]" in text
    assert "Judge.name: str" in text
    assert "merge(user_id, entity_type, keep_id, merge_ids, dry_run)" in text
    assert "protocol_version: 1" in text
