"""Hygiene (K§6).

Owners: H1a (ga-mxal.30) for this file, detect, routes; H1b (ga-mxal.31) for fixes.

block() is the entry the REST and MCP layers call when include_hygiene=true (K§6.2). It merges the
core and host detectors, drops what the user dismissed, sorts most severe first and cuts the list
to 10. dismiss() and resolve_tombstone() are the two writes H1a owns (K§6.3).
"""

from __future__ import annotations

from typing import Literal, get_args

from arp_notes import repo
from arp_notes.config import HostConfig
from arp_notes.hygiene import detect as detect_module
from arp_notes.models import (
    DismissResult,
    HygieneBlock,
    HygieneKind,
    ResolveTombstoneResult,
)

BLOCK_LIMIT = 10  # K§6.1: at most 10 issues per block
MAX_KEY_CHARS = 1000  # hygiene_dismissals.issue_key is btree-indexed

_SEVERITY_RANK = {"action": 0, "warn": 1, "info": 2}
_KINDS = frozenset(get_args(HygieneKind))


class InvalidIssueKey(repo.NotesError):
    """dismiss_issue got a key that cannot belong to any issue (K§6.1 shape)."""

    status = 422
    code = "invalid_issue_key"


class InvalidScope(repo.NotesError):
    status = 422
    code = "invalid_scope"


class NotTombstoned(repo.NotesError):
    """resolve_tombstone only applies to a note whose source was deleted."""

    status = 409
    code = "not_tombstoned"


def dismissed_keys(cfg: HostConfig, user_id: str) -> set[str]:
    rows = cfg.db.run("SELECT issue_key FROM hygiene_dismissals WHERE user_id = %s", [user_id])
    return {row["issue_key"] for row in rows}


def block(cfg: HostConfig, user_id: str, scope: str = "all") -> HygieneBlock:
    """scope: 'all' | 'note:<id>'. `total` counts every undismissed issue, `issues` the first 10."""
    try:
        issues = detect_module.collect(cfg, user_id, scope)
    except detect_module.InvalidScope as exc:
        raise InvalidScope(str(exc)) from exc
    dismissed = dismissed_keys(cfg, user_id)
    live = [issue for issue in issues if issue.key not in dismissed]
    live.sort(key=lambda issue: (_SEVERITY_RANK[issue.severity], issue.kind, issue.key))
    return HygieneBlock(
        issues=live[:BLOCK_LIMIT], total=len(live), truncated=len(live) > BLOCK_LIMIT
    )


def dismiss(
    cfg: HostConfig, user_id: str, issue_key: str, reason: str | None = None
) -> DismissResult:
    """Hide an issue until its subjects change (they get a new key then). Idempotent."""
    kind = issue_key.partition(":")[0]
    if kind not in _KINDS or len(issue_key) > MAX_KEY_CHARS or issue_key.count(":") < 2:
        raise InvalidIssueKey(
            f"{issue_key[:80]!r} is not an issue key; copy `key` from a hygiene issue",
        )
    cfg.db.run(
        "INSERT INTO hygiene_dismissals (user_id, issue_key, reason) VALUES (%s, %s, %s)"
        " ON CONFLICT (user_id, issue_key) DO NOTHING",
        [user_id, issue_key, reason],
    )
    return DismissResult(dismissed=True)


def resolve_tombstone(
    cfg: HostConfig, user_id: str, note_id: int, action: Literal["keep", "delete"]
) -> ResolveTombstoneResult:
    """K§6.3: 'keep' dismisses the tombstoned_note issue (the note stays hidden); 'delete' removes
    the note, its links and attachment rows for good. Only a tombstoned note qualifies, so a
    client LLM cannot use this to delete a live note. Raises NoteNotFound, NotTombstoned."""
    if action == "delete":
        # One statement, so a re-sync that revives the note cannot slip in between check and delete.
        deleted = cfg.db.run(
            "DELETE FROM notes WHERE id = %s AND user_id = %s AND deleted_at IS NOT NULL"
            " RETURNING id",
            [note_id, user_id],
        )
        if deleted:
            return ResolveTombstoneResult(note_id=note_id, action=action)
    rows = cfg.db.run(
        "SELECT deleted_at FROM notes WHERE id = %s AND user_id = %s", [note_id, user_id]
    )
    if not rows:
        raise repo.NoteNotFound(f"note {note_id} not found")
    if rows[0]["deleted_at"] is None:
        raise NotTombstoned(f"note {note_id} is not deleted at its source")
    if action == "keep":
        dismiss(cfg, user_id, f"tombstoned_note:note:{note_id}", "kept after source deletion")
        return ResolveTombstoneResult(note_id=note_id, action=action)
    # 'delete' found the note tombstoned yet deleted nothing: another caller removed it first.
    raise repo.NoteNotFound(f"note {note_id} not found")


__all__ = [
    "BLOCK_LIMIT",
    "InvalidIssueKey",
    "InvalidScope",
    "NotTombstoned",
    "block",
    "dismiss",
    "dismissed_keys",
    "resolve_tombstone",
]
