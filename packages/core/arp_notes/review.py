"""Review-state cache: notes.proposal + review_pending (K§3). Owner: R1 (ga-mxal.29).

`sync.upsert` calls `after_upsert`; the confirm routes call `apply_confirm`; the propose routes
call `propose`, which serves the cache and falls back to `enrich.propose` on a miss. The cache is
the last Proposal on the note (`notes.proposal`, `proposed_at`) and `review_pending` is the count
the "N to review" badges read.

The count is `len(links) + len(unresolved) + len(action_items)`. K§3 rule 2 also names
`len(ambiguous)`, but an ambiguous item is a ProposedLink with `candidates`, so it is already in
`links`; adding it again gives 27 for the mockup's 26 (filed as ga-mxal.43). `_count` is the one
place to change if the contract settles on another reading.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from pydantic import ValidationError

from arp_notes import enrich, repo
from arp_notes.config import HostConfig
from arp_notes.models import ConfirmBody, Proposal

log = logging.getLogger(__name__)


def _count(proposal: Proposal) -> int:
    return len(proposal.links) + len(proposal.unresolved) + len(proposal.action_items)


def _key(text: str | None, anchor: str | None) -> tuple[str, str]:
    return ((text or "").casefold(), anchor or "")


def _store(cfg: HostConfig, user_id: str, note_id: int, proposal: Proposal | None) -> int:
    """Write the cache and its count in one statement; None clears both. Returns the count."""
    if proposal is None:
        cfg.db.run(
            "UPDATE notes SET proposal = NULL, proposed_at = NULL, review_pending = 0"
            " WHERE id = %s AND user_id = %s",
            [note_id, user_id],
        )
        return 0
    pending = _count(proposal)
    # The hygiene block is per request (include_hygiene), never cached.
    payload = proposal.model_dump(mode="json", exclude={"hygiene", "cached"})
    cfg.db.run(
        "UPDATE notes SET proposal = %s::jsonb, proposed_at = %s, review_pending = %s"
        " WHERE id = %s AND user_id = %s",
        [json.dumps(payload), proposal.proposed_at, pending, note_id, user_id],
    )
    return pending


def _tombstoned(cfg: HostConfig, user_id: str, note_id: int) -> bool:
    rows = cfg.db.run(
        "SELECT deleted_at FROM notes WHERE id = %s AND user_id = %s", [note_id, user_id]
    )
    if not rows:
        raise repo.NoteNotFound(f"note {note_id} not found")
    return rows[0]["deleted_at"] is not None


def after_upsert(cfg: HostConfig, user_id: str, note_id: int, outcome: str) -> None:
    """Rule 1a and 6: recompute and cache the proposal after a created or updated upsert.

    `propose_on_sync` picks the depth: 'search' skips the judge so a sync never waits on AI,
    'judge' runs the full pipeline, 'off' does nothing. Tombstoned notes are never proposed.
    Never raises into the upsert: a failure is logged and the cache is left empty (an update
    drops the stale one, whose anchors no longer match the body).
    """
    mode = cfg.policy.propose_on_sync
    if outcome not in ("created", "updated") or mode == "off":
        return None
    try:
        if _tombstoned(cfg, user_id, note_id):
            return None
        proposal = enrich.propose(cfg, user_id, note_id, use_judge=mode == "judge")
        _store(cfg, user_id, note_id, proposal)
    except Exception:
        log.exception("review: auto-propose failed for note %s", note_id)
        try:
            _store(cfg, user_id, note_id, None)
        except Exception:
            log.exception("review: could not clear the stale proposal for note %s", note_id)
    return None


def get_cached(cfg: HostConfig, user_id: str, note_id: int) -> Proposal | None:
    """The cached Proposal with `cached=True`, or None when the note has never been proposed."""
    rows = cfg.db.run(
        "SELECT proposal, proposed_at FROM notes WHERE id = %s AND user_id = %s",
        [note_id, user_id],
    )
    if not rows:
        raise repo.NoteNotFound(f"note {note_id} not found")
    raw = rows[0]["proposal"]
    if raw is None:
        return None
    if isinstance(raw, str):
        raw = json.loads(raw)
    stamp = rows[0]["proposed_at"]
    try:
        return Proposal.model_validate(
            {
                **raw,
                "cached": True,
                "proposed_at": stamp.replace(microsecond=0).isoformat() if stamp else None,
            }
        )
    except ValidationError:
        log.warning("review: unreadable cached proposal on note %s, treating as a miss", note_id)
        return None


def propose(
    cfg: HostConfig, user_id: str, note_id: int, *, llm: bool = False, refresh: bool = False
) -> Proposal:
    """`POST /propose` with the cache in front (K§3 rule 1b, K§2 `refresh`).

    Returns the cached proposal unless `refresh` is set, there is none, or `llm` is set and the
    cache was built without the Layer 2 extraction. Otherwise runs the full pipeline, judge
    included, and caches the result. A tombstoned note is computed but not cached (rule 6).
    """
    if not refresh:
        cached = get_cached(cfg, user_id, note_id)
        if cached is not None and (not llm or "llm" in cached.generated_by):
            return cached
    proposal = enrich.propose(cfg, user_id, note_id, llm=llm, refresh=refresh)
    if not _tombstoned(cfg, user_id, note_id):
        _store(cfg, user_id, note_id, proposal)
    return proposal


def apply_confirm(cfg: HostConfig, user_id: str, note_id: int, body: ConfirmBody) -> dict[str, Any]:
    """Rule 3: drop everything the user saw except the deferred items, then recount.

    `deferred` names mentions as the review UI sends them: an ambiguous link by its `quote`, an
    unresolved mention by its `mention` text, each with its anchor. Confirmed, rejected and
    unticked items leave the cache (an unticked item is skipped: not persisted, not pending).
    `review_pending` is the number of distinct deferred mentions. Returns the ConfirmResult
    overlay, `{"review_pending": n}`.
    """
    wanted = {_key(d.mention, d.anchor) for d in body.deferred or []}
    with cfg.db.transaction():
        if _tombstoned(cfg, user_id, note_id):
            _store(cfg, user_id, note_id, None)
            return {"review_pending": 0}
        cached = get_cached(cfg, user_id, note_id)
        if cached is None:
            cfg.db.run(
                "UPDATE notes SET review_pending = %s WHERE id = %s AND user_id = %s",
                [len(wanted), note_id, user_id],
            )
            return {"review_pending": len(wanted)}
        kept = cached.model_copy(
            update={
                "links": [
                    link
                    for link in cached.links
                    if link.candidates and _key(link.quote, link.anchor) in wanted
                ],
                "unresolved": [
                    u
                    for u in cached.unresolved
                    if _key(u.mention, u.anchor) in wanted or _key(u.quote, u.anchor) in wanted
                ],
                "action_items": [],
                "takeaways": [],
            }
        )
        _store(cfg, user_id, note_id, kept)
        # Deferred mentions the cache no longer holds (a stale sheet) still count.
        cfg.db.run(
            "UPDATE notes SET review_pending = %s WHERE id = %s AND user_id = %s",
            [len(wanted), note_id, user_id],
        )
    return {"review_pending": len(wanted)}
