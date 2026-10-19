"""Markdown + attachments export (ADR §3.7). Owner: C3 (ga-mxal.10)."""

from __future__ import annotations

from typing import Any

from arp_notes.config import HostConfig


def export_note(
    cfg: HostConfig,
    user_id: str,
    note_id: int,
    with_enrichment: bool = False,
    style: str = "frontmatter",
) -> tuple[str, list[dict[str, Any]]]:
    """-> (markdown, attachment manifest). style: 'frontmatter' | 'companion'."""
    raise NotImplementedError("C3: export.export_note")
