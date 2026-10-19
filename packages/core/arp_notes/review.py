"""Review-state cache: notes.proposal + review_pending (K§3). Owner: R1 (ga-mxal.29).

sync.upsert calls after_upsert; the confirm route calls apply_confirm. C0 ships both as no-ops
that return nothing, so the call sites can be wired before R1 lands.
"""

from __future__ import annotations

from typing import Any

from arp_notes.config import HostConfig
from arp_notes.models import ConfirmBody, Proposal


def after_upsert(cfg: HostConfig, user_id: str, note_id: int, outcome: str) -> None:
    """No-op until R1."""
    return None


def get_cached(cfg: HostConfig, user_id: str, note_id: int) -> Proposal | None:
    raise NotImplementedError("R1: review.get_cached")


def apply_confirm(cfg: HostConfig, user_id: str, note_id: int, body: ConfirmBody) -> dict[str, Any]:
    """No-op until R1. Empty dict = no contribution to ConfirmResult (R1 adds review_pending)."""
    return {}
