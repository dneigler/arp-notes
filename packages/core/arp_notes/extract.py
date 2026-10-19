"""Layer 2 extraction: takeaways and action items. Owner: C5b (ga-mxal.27).

Needs policy.llm_enrich and hooks.llm_complete; the core imports no provider SDK.
"""

from __future__ import annotations

from typing import Any

from arp_notes.config import HostConfig
from arp_notes.models import Note, Proposal


def extract(cfg: HostConfig, note: Note, proposal: Proposal) -> dict[str, Any]:
    """-> {takeaways, action_items}"""
    raise NotImplementedError("C5b: extract.extract")
