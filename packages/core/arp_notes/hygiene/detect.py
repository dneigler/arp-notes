"""Core hygiene detectors (K§6.2). Owner: H1a (ga-mxal.30).

`detect` runs the five core detectors; `collect` adds the host's (`HostConfig.hygiene.detect`).
Neither filters dismissals nor limits the count: `hygiene.block` does that, and H1b's apply_fix
looks issues up through `collect`.

Every query is scoped to `user_id`. Scope is 'all' or 'note:<id>'; a collection-level detector
(unreferenced_blobs) stays out of a note scope.
"""

from __future__ import annotations

import hashlib
import logging
from typing import Any

from arp_notes.config import HostConfig
from arp_notes.models import HygieneFix, HygieneIssue, HygieneSubject

log = logging.getLogger(__name__)

# K§6.2 thresholds.
PENDING_REVIEW_DAYS = 7
UNREFERENCED_BLOB_DAYS = 30
# Keys go through a btree-indexed column (hygiene_dismissals), so a very large set of blob ids is
# digested instead of listed. Subjects shown to the client are capped for the same reason.
MAX_KEY_IDS = 100
MAX_SUBJECTS = 20


class InvalidScope(ValueError):
    """scope is neither 'all' nor 'note:<id>'."""


def parse_scope(scope: str) -> int | None:
    """-> the note id for 'note:<id>', None for 'all'. Raises InvalidScope."""
    if scope == "all":
        return None
    kind, sep, rest = scope.partition(":")
    if kind == "note" and sep and rest.isascii() and rest.isdigit():
        return int(rest)
    raise InvalidScope(f"scope must be 'all' or 'note:<id>', got {scope!r}")


def _note_subject(row: dict[str, Any]) -> HygieneSubject:
    return HygieneSubject(entity_type="note", entity_id=row["id"], label=row["title"])


def _dismiss_fix(key: str) -> HygieneFix:
    # Nothing is changed or lost, and the issue comes back if its subjects change (K§6.1).
    return HygieneFix(
        label="Not now: hide this suggestion",
        tool="dismiss_issue",
        arguments={"issue_key": key},
        dry_run_first=False,
        reversible=True,
    )


def _note_scope_sql(note_id: int | None, column: str = "id") -> tuple[str, list[Any]]:
    return ("", []) if note_id is None else (f" AND {column} = %s", [note_id])


def _tombstoned(cfg: HostConfig, user_id: str, note_id: int | None) -> list[HygieneIssue]:
    extra, params = _note_scope_sql(note_id)
    rows = cfg.db.run(
        "SELECT id, title FROM notes WHERE user_id = %s AND deleted_at IS NOT NULL"
        f"{extra} ORDER BY id",
        [user_id, *params],
    )
    issues = []
    for row in rows:
        key = f"tombstoned_note:note:{row['id']}"
        issues.append(
            HygieneIssue(
                key=key,
                kind="tombstoned_note",
                severity="action",
                title=f"The source of “{row['title']}” was deleted",
                explanation=(
                    f"The note “{row['title']}” was deleted where it came from (for example in "
                    "Obsidian or Notion). This app keeps a hidden copy, with its links, until "
                    "someone decides. Keeping the copy leaves it out of feeds and lists; "
                    "deleting it removes it and its links for good."
                ),
                subjects=[_note_subject(row)],
                fixes=[
                    HygieneFix(
                        label="Keep the copy here",
                        tool="resolve_tombstone",
                        arguments={"note_id": row["id"], "action": "keep"},
                        dry_run_first=False,
                        reversible=True,
                    ),
                    HygieneFix(
                        label="Delete the copy and its links",
                        tool="resolve_tombstone",
                        arguments={"note_id": row["id"], "action": "delete"},
                        dry_run_first=False,
                        reversible=False,
                    ),
                ],
                detected_by="core",
            )
        )
    return issues


def _pending_review(cfg: HostConfig, user_id: str, note_id: int | None) -> list[HygieneIssue]:
    extra, params = _note_scope_sql(note_id)
    rows = cfg.db.run(
        "SELECT id, title, review_pending FROM notes"
        " WHERE user_id = %s AND deleted_at IS NULL AND review_pending > 0"
        f" AND proposed_at < CURRENT_TIMESTAMP - INTERVAL '{PENDING_REVIEW_DAYS} days'"
        f"{extra} ORDER BY id",
        [user_id, *params],
    )
    issues = []
    for row in rows:
        key = f"pending_review:note:{row['id']}"
        count = row["review_pending"]
        issues.append(
            HygieneIssue(
                key=key,
                kind="pending_review",
                severity="info",
                title=f"{_items(count)} to review in “{row['title']}” for over a week",
                explanation=(
                    f"The note “{row['title']}” has {_items(count)} suggested links, action "
                    f"items or open questions that nobody has accepted or rejected in more than "
                    f"{PENDING_REVIEW_DAYS} days. Nothing is lost; they simply wait for a decision."
                ),
                subjects=[_note_subject(row)],
                fixes=[
                    HygieneFix(
                        label="Show the suggestions to review with the user",
                        tool="propose_note_enrichment",
                        arguments={"note_id": row["id"]},
                        dry_run_first=False,
                        reversible=True,
                    ),
                    _dismiss_fix(key),
                ],
                detected_by="core",
            )
        )
    return issues


def _orphaned_links(cfg: HostConfig, user_id: str, note_id: int | None) -> list[HygieneIssue]:
    extra, params = _note_scope_sql(note_id, "n.id")
    rows = cfg.db.run(
        "SELECT n.id, n.title, COUNT(*) AS orphaned FROM note_links l"
        " JOIN notes n ON n.id = l.note_id"
        " WHERE l.user_id = %s AND n.user_id = %s AND l.status = 'orphaned'"
        f" AND n.deleted_at IS NULL{extra} GROUP BY n.id, n.title ORDER BY n.id",
        [user_id, user_id, *params],
    )
    issues = []
    for row in rows:
        key = f"orphaned_links:note:{row['id']}"
        count = row["orphaned"]
        noun = "link" if count == 1 else "links"
        issues.append(
            HygieneIssue(
                key=key,
                kind="orphaned_links",
                severity="warn",
                title=f"{count} {noun} in “{row['title']}” lost their place",
                explanation=(
                    f"{count} confirmed {noun} in “{row['title']}” pointed at a heading or passage "
                    "that no longer exists after the note changed, so they no longer show next to "
                    "any text. Running the suggestions again can re-attach them to the new text."
                ),
                subjects=[_note_subject(row)],
                fixes=[
                    HygieneFix(
                        label="Run the suggestions again for this note",
                        tool="propose_note_enrichment",
                        arguments={"note_id": row["id"], "refresh": True},
                        dry_run_first=False,
                        reversible=True,
                    ),
                    _dismiss_fix(key),
                ],
                detected_by="core",
            )
        )
    return issues


def _blob_key(ids: list[int]) -> str:
    if len(ids) <= MAX_KEY_IDS:
        return "unreferenced_blobs:blob:" + ",".join(str(i) for i in ids)
    digest = hashlib.sha256(",".join(str(i) for i in ids).encode()).hexdigest()[:16]
    return f"unreferenced_blobs:blob:{len(ids)}+{digest}"


def _unreferenced_blobs(cfg: HostConfig, user_id: str) -> list[HygieneIssue]:
    rows = cfg.db.run(
        "SELECT b.id, b.sha256, b.mime, b.size_bytes FROM blobs b"
        f" WHERE b.user_id = %s AND b.created_at < CURRENT_TIMESTAMP"
        f" - INTERVAL '{UNREFERENCED_BLOB_DAYS} days'"
        " AND NOT EXISTS (SELECT 1 FROM note_attachments a WHERE a.blob_id = b.id)"
        " ORDER BY b.id",
        [user_id],
    )
    if not rows:
        return []
    ids = sorted(row["id"] for row in rows)
    key = _blob_key(ids)
    total_bytes = sum(row["size_bytes"] or 0 for row in rows)
    noun = "file" if len(rows) == 1 else "files"
    subjects = [
        HygieneSubject(
            entity_type="blob",
            entity_id=row["id"],
            label=f"{row['mime']} {row['sha256'][:8]}",
        )
        for row in rows[:MAX_SUBJECTS]
    ]
    return [
        HygieneIssue(
            key=key,
            kind="unreferenced_blobs",
            severity="info",
            title=f"{len(rows)} stored {noun} no note uses",
            explanation=(
                f"{len(rows)} stored attachment {noun} ({_size(total_bytes)} in all) are not "
                f"embedded in any note and have been sitting for more than "
                f"{UNREFERENCED_BLOB_DAYS} days, typically left behind when a note changed. "
                "They can be deleted to free the space."
            ),
            subjects=subjects,
            fixes=[
                HygieneFix(
                    label=f"Delete the {len(rows)} unused {noun}",
                    tool="apply_fix",
                    arguments={"issue_key": key, "fix_index": 0},
                    dry_run_first=True,
                    reversible=False,
                ),
                _dismiss_fix(key),
            ],
            detected_by="core",
        )
    ]


def _unresolved_mentions(cfg: HostConfig, user_id: str, note_id: int | None) -> list[HygieneIssue]:
    extra, params = _note_scope_sql(note_id)
    # CASE keeps jsonb_array_length away from a proposal whose `unresolved` is not an array.
    count_sql = (
        "CASE WHEN jsonb_typeof(proposal -> 'unresolved') = 'array'"
        " THEN jsonb_array_length(proposal -> 'unresolved') ELSE 0 END"
    )
    rows = cfg.db.run(
        f"SELECT id, title, {count_sql} AS unresolved FROM notes"
        f" WHERE user_id = %s AND deleted_at IS NULL AND proposal IS NOT NULL"
        f" AND {count_sql} > 0{extra} ORDER BY id",
        [user_id, *params],
    )
    issues = []
    for row in rows:
        key = f"unresolved_mentions:note:{row['id']}"
        count = row["unresolved"]
        noun = "mention" if count == 1 else "mentions"
        issues.append(
            HygieneIssue(
                key=key,
                kind="unresolved_mentions",
                severity="info",
                title=f"{count} {noun} in “{row['title']}” match nothing in the library",
                explanation=(
                    f"The last suggestions for “{row['title']}” found {count} {noun} of pieces, "
                    "composers or techniques that the app could not match to anything it knows. "
                    "They may be missing from the library, or spelled differently from how the "
                    "library names them."
                ),
                subjects=[_note_subject(row)],
                fixes=[
                    HygieneFix(
                        label="Show the unmatched mentions to review with the user",
                        tool="propose_note_enrichment",
                        arguments={"note_id": row["id"]},
                        dry_run_first=False,
                        reversible=True,
                    ),
                    _dismiss_fix(key),
                ],
                detected_by="core",
            )
        )
    return issues


def _items(count: int) -> str:
    return f"{count} item" if count == 1 else f"{count} items"


def _size(n: int) -> str:
    size = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{n} B"  # unreachable; keeps the type checker content


def detect(cfg: HostConfig, user_id: str, scope: str = "all") -> list[HygieneIssue]:
    """The core detectors' issues for `scope`, in no particular order. Raises InvalidScope."""
    note_id = parse_scope(scope)
    issues = [
        *_tombstoned(cfg, user_id, note_id),
        *_pending_review(cfg, user_id, note_id),
        *_orphaned_links(cfg, user_id, note_id),
        *_unresolved_mentions(cfg, user_id, note_id),
    ]
    if note_id is None:
        issues.extend(_unreferenced_blobs(cfg, user_id))
    return issues


def host_issues(cfg: HostConfig, user_id: str, scope: str = "all") -> list[HygieneIssue]:
    """What `cfg.hygiene.detect` returns, validated and marked detected_by='host'.

    A host detector that raises, or returns something that is not an issue, is logged and
    skipped: a broken host detector must not hide the core ones.
    """
    if cfg.hygiene is None:
        return []
    try:
        found = list(cfg.hygiene.detect(user_id, scope))
    except Exception:
        log.exception("Hygiene.detect failed for scope %s", scope)
        return []
    issues = []
    for item in found:
        try:
            issue = HygieneIssue.model_validate(
                item.model_dump() if isinstance(item, HygieneIssue) else item
            )
        except Exception:
            log.exception("Hygiene.detect returned an invalid issue: %r", item)
            continue
        issues.append(issue.model_copy(update={"detected_by": "host"}))
    return issues


def collect(cfg: HostConfig, user_id: str, scope: str = "all") -> list[HygieneIssue]:
    """Core plus host issues, one per key (core wins), before dismissal and the 10-issue cap."""
    seen: set[str] = set()
    out: list[HygieneIssue] = []
    for issue in [*detect(cfg, user_id, scope), *host_issues(cfg, user_id, scope)]:
        if issue.key not in seen:
            seen.add(issue.key)
            out.append(issue)
    return out
