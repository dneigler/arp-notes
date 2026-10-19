"""manifest / upsert / tombstone (ADR §3.2, A.2). Owner: C1b (ga-mxal.8).

The source owns the body; the app owns the enrichment (links). A note is identified by
`(source_system, source_workspace, source_doc_id)` per user, never by path.

upsert calls `review.after_upsert` (K§3) and `Hooks.on_event`, both after the commit.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Sequence
from typing import Any

from arp_notes import review
from arp_notes.anchors import slug
from arp_notes.config import HostConfig
from arp_notes.models import (
    ManifestPage,
    ManifestRow,
    NoteUpsert,
    TombstoneResult,
    UpsertAttachment,
    UpsertResult,
)
from arp_notes.repo import emit_event, find_blob_ids, source_label

log = logging.getLogger(__name__)

MAX_MANIFEST_PAGE = 500

_ATX_HEADING = re.compile(r"^[ \t]*(?:>[ \t]*)*#{1,6}[ \t]+(.*?)[ \t]*$")
_ATX_CLOSING = re.compile(r"[ \t]+#+$")
_SETEXT_UNDERLINE = re.compile(r"^[ \t]{0,3}(?:=+|-+)[ \t]*$")
_BLOCK_ID = re.compile(r"(?:^|\s)(\^[A-Za-z0-9-]+)\s*$")
_FENCE = re.compile(r"^[ \t]*(`{3,}|~{3,})")
_NOT_SETEXT_TEXT = re.compile(r"^[ \t]*(?:#|>|[-*+][ \t]|\d+[.)][ \t]|`{3}|~{3})")


# ---------------------------------------------------------------------------------------------
# Anchors
# ---------------------------------------------------------------------------------------------


def _skip_frontmatter(lines: list[str]) -> int:
    """Index of the first line after a leading YAML frontmatter block, else 0."""
    if not lines or lines[0].lstrip("﻿").rstrip() != "---":
        return 0
    for i in range(1, len(lines)):
        if lines[i].rstrip() in ("---", "..."):
            return i + 1
    return 0


def body_anchors(body_md: str) -> set[str]:
    """Every anchor a link could point at in `body_md`: heading slugs and '^block-id's.

    Skips the frontmatter block and fenced code. It errs toward finding too many (setext
    headings, headings inside quotes), because a missing anchor orphans a link and an extra one
    only keeps it.
    """
    lines = body_md.split("\n")
    anchors: set[str] = set()
    fence: str | None = None
    for i in range(_skip_frontmatter(lines), len(lines)):
        line = lines[i].rstrip("\r")
        opened = _FENCE.match(line)
        if opened:
            marker = opened.group(1)[0]
            if fence is None:
                fence = marker
            elif fence == marker:
                fence = None
            continue
        if fence is not None:
            continue
        heading = _ATX_HEADING.match(line)
        if heading:
            text = _ATX_CLOSING.sub("", heading.group(1)).strip()
            if text:
                anchors.add(slug(text))
        elif (
            line.strip()
            and not _NOT_SETEXT_TEXT.match(line)
            and i + 1 < len(lines)
            and _SETEXT_UNDERLINE.match(lines[i + 1].rstrip("\r"))
        ):
            anchors.add(slug(line.strip()))
        block = _BLOCK_ID.search(line)
        if block:
            anchors.add(block.group(1))
    return anchors


def _revalidate_links(cfg: HostConfig, note_id: int, body_md: str) -> int:
    """Orphan confirmed links whose anchor left the body; restore orphaned ones that returned.

    Never deletes. Whole-note links (no anchor) are not tied to the body, so they are restored
    when a tombstoned note comes back. Rejected links are suppression markers and are left
    alone. -> the number newly orphaned.
    """
    anchors = body_anchors(body_md)
    rows = cfg.db.run(
        "SELECT id, anchor, status FROM note_links WHERE note_id = %s"
        " AND status IN ('confirmed', 'orphaned')",
        [note_id],
    )
    orphan = [
        r["id"]
        for r in rows
        if r["status"] == "confirmed" and r["anchor"] is not None and r["anchor"] not in anchors
    ]
    restore = [
        r["id"]
        for r in rows
        if r["status"] == "orphaned" and (r["anchor"] is None or r["anchor"] in anchors)
    ]
    if orphan:
        cfg.db.run(
            "UPDATE note_links SET status = 'orphaned', updated_at = CURRENT_TIMESTAMP"
            " WHERE id = ANY(%s)",
            [orphan],
        )
    if restore:
        cfg.db.run(
            "UPDATE note_links SET status = 'confirmed', updated_at = CURRENT_TIMESTAMP"
            " WHERE id = ANY(%s)",
            [restore],
        )
    return len(orphan)


# ---------------------------------------------------------------------------------------------
# Manifest
# ---------------------------------------------------------------------------------------------


def manifest(
    cfg: HostConfig,
    user_id: str,
    source_system: str,
    source_workspace: str,
    limit: int = 50,
    after: str | None = None,
) -> ManifestPage:
    """A.2 `GET /notes/sync/manifest`: what the server holds for one source workspace.

    Ordered by source_doc_id; `after` is the last id of the previous page and `next_after` is set
    when more follow. `limit` is clamped to 1..500. Tombstoned notes are included with their
    `deleted_at`, so a client can tell "deleted" from "never synced".
    """
    limit = max(1, min(limit, MAX_MANIFEST_PAGE))
    where = [
        "user_id = %s",
        "source_system = %s",
        "source_workspace = %s",
        "source_doc_id IS NOT NULL",
        "content_hash IS NOT NULL",
    ]
    params: list[Any] = [user_id, source_system, source_workspace]
    if after is not None:
        where.append("source_doc_id > %s")
        params.append(after)
    rows = cfg.db.run(
        "SELECT id, source_doc_id, source_path, content_hash, last_synced_at, deleted_at,"
        f" created_at FROM notes WHERE {' AND '.join(where)} ORDER BY source_doc_id LIMIT %s",
        [*params, limit + 1],
    )
    page, more = rows[:limit], len(rows) > limit
    shas: dict[int, list[str]] = {row["id"]: [] for row in page}
    if page:
        for att in cfg.db.run(
            "SELECT a.note_id, b.sha256 FROM note_attachments a JOIN blobs b ON b.id = a.blob_id"
            " WHERE a.note_id = ANY(%s) ORDER BY a.sort_order, a.id",
            [list(shas)],
        ):
            if att["sha256"] not in shas[att["note_id"]]:
                shas[att["note_id"]].append(att["sha256"])
    return ManifestPage(
        items=[
            ManifestRow.model_validate(
                {
                    "source_doc_id": row["source_doc_id"],
                    "source_path": row["source_path"] or "",
                    "content_hash": row["content_hash"],
                    "attachments": shas[row["id"]],
                    "last_synced_at": row["last_synced_at"] or row["created_at"],
                    "deleted_at": row["deleted_at"],
                }
            )
            for row in page
        ],
        next_after=page[-1]["source_doc_id"] if more else None,
    )


# ---------------------------------------------------------------------------------------------
# Upsert
# ---------------------------------------------------------------------------------------------

_IDENTITY = "user_id = %s AND source_system = %s AND source_workspace = %s AND source_doc_id = %s"


def _sync_attachments(
    cfg: HostConfig, note_id: int, wanted: Sequence[UpsertAttachment], blob_ids: dict[str, int]
) -> None:
    """Make note_attachments match `wanted`, keyed by ref_in_markdown.

    Rows keep their ids when only unrelated refs change. An attachment whose blob is not
    uploaded yet gets no row (blob_id is NOT NULL); the caller reports it as missing and the
    client re-upserts after uploading.
    """
    ready = [(i, a) for i, a in enumerate(wanted) if a.sha256 in blob_ids]
    cfg.db.run(
        "DELETE FROM note_attachments WHERE note_id = %s AND NOT (ref_in_markdown = ANY(%s))",
        [note_id, [a.ref_in_markdown for _, a in ready]],
    )
    for order, att in ready:
        cfg.db.run(
            "INSERT INTO note_attachments (note_id, blob_id, filename, ref_in_markdown, sort_order)"
            " VALUES (%s, %s, %s, %s, %s) ON CONFLICT (note_id, ref_in_markdown)"
            " DO UPDATE SET blob_id = EXCLUDED.blob_id, filename = EXCLUDED.filename,"
            " sort_order = EXCLUDED.sort_order",
            [note_id, blob_ids[att.sha256], att.filename, att.ref_in_markdown, order],
        )


def upsert(
    cfg: HostConfig, user_id: str, body: NoteUpsert, *, created_via: str = "cli"
) -> UpsertResult:
    """A.2 `POST /notes/sync/upsert`, idempotent on the identity triple.

    - `created`: no note has the triple. `updated`: the content_hash differs (or a tombstoned
      note came back). `unchanged`: same hash; the path, URL and last_synced_at still follow the
      source, so a rename keeps the id and updates source_path/source_url.
    - On update title, body, frontmatter, URL and attachments are replaced. kind, person,
      note_date and place change only when the request supplies them (a user may have edited
      them in the app).
    - Attachments whose sha256 has no blob yet are returned in `missing_attachments`; upload them
      and upsert again. The attachment rows are reconciled on every call, `unchanged` included.
    - Links whose anchor left the body become 'orphaned' (never deleted) and are counted in
      `links_orphaned`.
    - After the commit, a created or updated note emits `note_synced` and calls
      `review.after_upsert`. Both are best effort: a failure is logged, not raised.
    """
    by_ref: dict[str, UpsertAttachment] = {}
    for att in body.attachments:
        by_ref.setdefault(att.ref_in_markdown, att)  # the first of a repeated ref wins
    wanted = list(by_ref.values())
    links_orphaned = 0
    with cfg.db.transaction():
        blob_ids = find_blob_ids(cfg, user_id, (a.sha256 for a in wanted))
        missing = list(dict.fromkeys(a.sha256 for a in wanted if a.sha256 not in blob_ids))
        identity = [user_id, body.source_system, body.source_workspace, body.source_doc_id]
        existing = cfg.db.run(
            f"SELECT id, content_hash, deleted_at FROM notes WHERE {_IDENTITY} FOR UPDATE",
            identity,
        )
        note_id = 0
        outcome = "created"
        if not existing:
            created = cfg.db.run(
                "INSERT INTO notes (user_id, kind, title, body_md, frontmatter, person,"
                " note_date, place, origin, source_system, source_workspace, source_doc_id,"
                " source_path, source_url, source_modified_at, content_hash, last_synced_at,"
                " created_via, version) VALUES (%s, %s, %s, %s, %s::jsonb, %s, %s, %s, 'source',"
                " %s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP, %s, 1)"
                " ON CONFLICT (user_id, source_system, source_workspace, source_doc_id)"
                " WHERE source_doc_id IS NOT NULL DO NOTHING RETURNING id",
                [
                    user_id,
                    body.kind or "note",
                    body.title,
                    body.body_md,
                    json.dumps(body.frontmatter or {}),
                    body.person,
                    body.note_date,
                    body.place,
                    body.source_system,
                    body.source_workspace,
                    body.source_doc_id,
                    body.source_path,
                    body.source_url,
                    body.source_modified_at,
                    body.content_hash,
                    created_via,
                ],
            )
            if created:
                note_id = created[0]["id"]
            else:  # another request created it between our SELECT and INSERT
                existing = cfg.db.run(
                    f"SELECT id, content_hash, deleted_at FROM notes WHERE {_IDENTITY} FOR UPDATE",
                    identity,
                )
        if existing:
            note_id = existing[0]["id"]
            changed = (
                existing[0]["content_hash"] != body.content_hash
                or existing[0]["deleted_at"] is not None
            )
            if changed:
                outcome = "updated"
                cfg.db.run(
                    "UPDATE notes SET title = %s, body_md = %s, frontmatter = %s::jsonb,"
                    " kind = COALESCE(%s, kind), person = COALESCE(%s, person),"
                    " note_date = COALESCE(%s, note_date), place = COALESCE(%s, place),"
                    " source_path = %s, source_url = %s, source_modified_at = %s,"
                    " content_hash = %s, last_synced_at = CURRENT_TIMESTAMP, deleted_at = NULL,"
                    " updated_at = CURRENT_TIMESTAMP WHERE id = %s",
                    [
                        body.title,
                        body.body_md,
                        json.dumps(body.frontmatter or {}),
                        body.kind,
                        body.person,
                        body.note_date,
                        body.place,
                        body.source_path,
                        body.source_url,
                        body.source_modified_at,
                        body.content_hash,
                        note_id,
                    ],
                )
                links_orphaned = _revalidate_links(cfg, note_id, body.body_md)
            else:
                outcome = "unchanged"
                cfg.db.run(
                    "UPDATE notes SET source_path = %s, source_url = %s,"
                    " source_modified_at = COALESCE(%s, source_modified_at),"
                    " last_synced_at = CURRENT_TIMESTAMP WHERE id = %s",
                    [body.source_path, body.source_url, body.source_modified_at, note_id],
                )
        _sync_attachments(cfg, note_id, wanted, blob_ids)

    if outcome != "unchanged":
        row = {"source_system": body.source_system, "source_workspace": body.source_workspace}
        emit_event(
            cfg,
            user_id,
            "note_synced",
            note_id,
            f"Note synced from {source_label(row)}: {body.title}",
        )
        try:
            review.after_upsert(cfg, user_id, note_id, outcome)
        except Exception:
            log.exception("review.after_upsert failed for note %s", note_id)
    return UpsertResult(
        note_id=note_id,
        outcome=outcome,  # type: ignore[arg-type]
        missing_attachments=missing,
        links_orphaned=links_orphaned,
    )


# ---------------------------------------------------------------------------------------------
# Tombstone
# ---------------------------------------------------------------------------------------------


def tombstone(
    cfg: HostConfig,
    user_id: str,
    source_system: str,
    source_workspace: str,
    source_doc_ids: Sequence[str],
) -> TombstoneResult:
    """A.2 `POST /notes/sync/tombstone`: the source deleted these notes.

    Sets `deleted_at`, keeps the body and turns confirmed links into 'orphaned' so the note can
    still be reached from the pieces it covers; `review_pending` goes to 0 (K§3.6). Ids the
    server has no note for come back in `unknown`. A note that is already tombstoned is left
    alone and not counted again. Emits `note_tombstoned` for each note newly tombstoned.
    """
    done: list[int] = []
    unknown: list[str] = []
    with cfg.db.transaction():
        for doc_id in dict.fromkeys(source_doc_ids):
            rows = cfg.db.run(
                f"SELECT id, deleted_at FROM notes WHERE {_IDENTITY} FOR UPDATE",
                [user_id, source_system, source_workspace, doc_id],
            )
            if not rows:
                unknown.append(doc_id)
            elif rows[0]["deleted_at"] is None:
                note_id = rows[0]["id"]
                cfg.db.run(
                    "UPDATE notes SET deleted_at = CURRENT_TIMESTAMP, review_pending = 0,"
                    " updated_at = CURRENT_TIMESTAMP WHERE id = %s",
                    [note_id],
                )
                cfg.db.run(
                    "UPDATE note_links SET status = 'orphaned', updated_at = CURRENT_TIMESTAMP"
                    " WHERE note_id = %s AND status = 'confirmed'",
                    [note_id],
                )
                done.append(note_id)
    for note_id in done:
        emit_event(cfg, user_id, "note_tombstoned", note_id, "Note deleted at its source")
    return TombstoneResult(tombstoned=len(done), unknown=unknown)
