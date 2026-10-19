"""apply_fix and merge_entities: dry run first, confirm_token, audited (K§6.3).

Owner: H1b (ga-mxal.31).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from arp_notes.config import HostConfig
from arp_notes.models import MergePlan

router = APIRouter()


def apply_fix(
    cfg: HostConfig, user_id: str, issue_key: str, fix_index: int, confirm_token: str | None = None
) -> dict[str, Any]:
    raise NotImplementedError("H1b: fixes.apply_fix")


def merge_entities(
    cfg: HostConfig,
    user_id: str,
    entity_type: str,
    keep_id: int,
    merge_ids: list[int],
    dry_run: bool = True,
    confirm_token: str | None = None,
) -> MergePlan | dict[str, Any]:
    raise NotImplementedError("H1b: fixes.merge_entities")
