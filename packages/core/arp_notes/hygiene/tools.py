"""Hygiene MCP tool specs: dismiss_issue, resolve_tombstone (H1a), apply_fix, merge_entities (H1b).

arp_notes.mcp.TOOLS imports TOOLS from here.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from arp_notes.mcp import ToolSpec

TOOLS: list[ToolSpec] = []
