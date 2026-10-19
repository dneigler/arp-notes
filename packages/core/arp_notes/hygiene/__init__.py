"""Hygiene (K§6).

Owners: H1a (ga-mxal.30) for this file, detect, routes; H1b (ga-mxal.31) for fixes.

block() is the entry the REST and MCP layers call when include_hygiene=true (K§6.2). C0 ships it
as a no-op returning an empty block.
"""

from __future__ import annotations

from arp_notes.config import HostConfig
from arp_notes.models import HygieneBlock


def block(cfg: HostConfig, user_id: str, scope: str = "all") -> HygieneBlock:
    """scope: 'all' | 'note:<id>'. Empty until H1a."""
    return HygieneBlock.model_validate({"issues": [], "total": 0, "truncated": False})
