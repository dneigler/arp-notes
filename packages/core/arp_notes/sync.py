"""manifest / upsert / tombstone (ADR §3.2, A.2). Owner: C1b (ga-mxal.8).

upsert calls review.after_upsert(...) (K§3) and Hooks.on_event.
"""

from __future__ import annotations

from collections.abc import Sequence

from arp_notes.config import HostConfig
from arp_notes.models import ManifestPage, NoteUpsert, TombstoneResult, UpsertResult


def manifest(
    cfg: HostConfig,
    user_id: str,
    source_system: str,
    source_workspace: str,
    limit: int = 50,
    after: str | None = None,
) -> ManifestPage:
    raise NotImplementedError("C1b: sync.manifest")


def upsert(cfg: HostConfig, user_id: str, body: NoteUpsert) -> UpsertResult:
    raise NotImplementedError("C1b: sync.upsert")


def tombstone(
    cfg: HostConfig,
    user_id: str,
    source_system: str,
    source_workspace: str,
    source_doc_ids: Sequence[str],
) -> TombstoneResult:
    raise NotImplementedError("C1b: sync.tombstone")
