"""notes/links/blobs/tickets CRUD over the Db port. Owner: C1b (ga-mxal.8).

Raw SQL through `HostConfig.db` (`%s` placeholders; ORM-free, no app globals, no connections of
its own). Every query is scoped by `user_id`. The functions here return the Pydantic models from
`arp_notes.models`; the routers (C3) and MCP handlers (C4) turn them into responses.

Errors. Failures a client can act on raise a `NotesError` subclass that carries the HTTP status
and the `{"error": code}` body A.2 and K§2 use, so the routers map them with no logic of their own.

Hooks. `emit_event` is the one place `Hooks.on_event(user_id, event_type, entity, summary)` is
called. `entity` is a flat dict: `{"entity_type": "note", "entity_id": <note id>, **payload}`,
where the payload is the K§10 shape (`event, note_id, note_title, kind, person?, origin,
source_system?, source_workspace?, link_count, attachment_count`, plus `links_created?`,
`backlog_created?`, `rejected?`, `deferred?` on `note_enriched`). The PT adapter writes the
activity row with entity_type/entity_id and the rest as `details_json`. Events fire after the
transaction commits and a failing hook is logged, never raised.
"""

from __future__ import annotations

import base64
import binascii
import json
import logging
import re
from collections import defaultdict
from collections.abc import Iterable, Sequence
from datetime import datetime
from typing import Any

from arp_notes.config import HostConfig
from arp_notes.models import (
    Attachment,
    AutosaveBody,
    AutosaveResult,
    ConfirmBody,
    ConfirmResult,
    EntityNote,
    EntityNotes,
    Note,
    NoteCreate,
    NoteLink,
    NoteList,
    NotePatch,
    NoteSummary,
    SyncSource,
)
from arp_notes.ports import LinkSchemes, SchemeChildren

log = logging.getLogger(__name__)

MAX_PAGE = 100
TOP_LINKS = 4
_MAX_CHILD_DEPTH = 3
_MAX_CHILD_NODES = 500

# K§2 top_links order: works before movements before composers. The names are the host
# vocabulary PT uses; anything else sorts last.
_TOP_LINK_RANK = {"repertoire": 0, "work": 0, "movement": 1, "section": 1, "composer": 2}


# ---------------------------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------------------------


class NotesError(Exception):
    """Base for failures with an HTTP status and an `{"error": code}` body."""

    status = 400
    code = "error"

    def __init__(self, message: str | None = None, **extra: Any) -> None:
        super().__init__(message or self.code)
        self.extra = extra

    @property
    def body(self) -> dict[str, Any]:
        return {"error": self.code, **self.extra}


class NoteNotFound(NotesError):
    status = 404
    code = "not_found"


class ReadOnlyImport(NotesError):
    """origin='source' notes only accept kind/person/note_date/place edits (A.2)."""

    status = 409
    code = "read_only_import"


class TakeawayNeedsLink(NotesError):
    """A takeaway whose anchor has no confirmed link (architect default, bead ga-mxal.8)."""

    status = 422
    code = "takeaway_needs_link"


class ActionNeedsLink(NotesError):
    """An action item with no link_index, no entity and no confirmed link at its anchor."""

    status = 422
    code = "action_needs_link"


class InvalidLinkIndex(NotesError):
    status = 422
    code = "invalid_link_index"


class SomedayUnsupported(NotesError):
    status = 422
    code = "someday_unsupported"


class InvalidCursor(NotesError):
    status = 422
    code = "invalid_cursor"


# ---------------------------------------------------------------------------------------------
# Small helpers shared with sync.py
# ---------------------------------------------------------------------------------------------


def as_json(value: Any, default: Any = None) -> Any:
    """A JSONB column as Python. Drivers differ on whether they decode it."""
    if isinstance(value, str):
        try:
            return json.loads(value)
        except ValueError:
            return default
    return default if value is None else value


def _confidence(value: Any) -> float | None:
    # `confidence` is REAL (float4): 0.8 reads back as 0.800000011920929.
    return None if value is None else round(float(value), 4)


def scheme_for(cfg: HostConfig, entity_type: str) -> LinkSchemes | None:
    for scheme in cfg.schemes:
        if entity_type in scheme.entity_types:
            return scheme
    return None


class Labeler:
    """entity_label via `LinkSchemes.resolve`, memoised for one request."""

    def __init__(self, cfg: HostConfig, user_id: str) -> None:
        self._cfg = cfg
        self._user_id = user_id
        self._memo: dict[tuple[str, int], str] = {}

    def label(self, entity_type: str, entity_id: int) -> str:
        key = (entity_type, entity_id)
        if key not in self._memo:
            self._memo[key] = self._resolve(entity_type, entity_id)
        return self._memo[key]

    def _resolve(self, entity_type: str, entity_id: int) -> str:
        fallback = f"{entity_type} #{entity_id}"
        scheme = scheme_for(self._cfg, entity_type)
        if scheme is None:
            return fallback
        try:
            found = scheme.resolve(self._user_id, entity_type, entity_id)
        except Exception:
            # A label is display data; a broken scheme must not take the whole read down.
            log.exception("LinkSchemes.resolve failed for %s/%s", entity_type, entity_id)
            return fallback
        title = found.get("title") if found else None
        return str(title) if title else fallback


def emit_event(
    cfg: HostConfig,
    user_id: str,
    event_type: str,
    note_id: int,
    summary: str,
    **extra: Any,
) -> None:
    """Call `Hooks.on_event` with the K§10 payload. Never raises."""
    hooks = cfg.hooks
    if hooks is None or hooks.on_event is None:
        return
    try:
        rows = cfg.db.run(
            "SELECT n.title, n.kind, n.person, n.origin, n.source_system, n.source_workspace,"
            " (SELECT COUNT(*) FROM note_links l WHERE l.note_id = n.id AND l.status = 'confirmed')"
            "   AS link_count,"
            " (SELECT COUNT(*) FROM note_attachments a WHERE a.note_id = n.id)"
            "   AS attachment_count"
            " FROM notes n WHERE n.id = %s AND n.user_id = %s",
            [note_id, user_id],
        )
        if not rows:
            return
        row = rows[0]
        payload: dict[str, Any] = {
            "event": event_type,
            "note_id": note_id,
            "note_title": row["title"],
            "kind": row["kind"],
            "origin": row["origin"],
            "link_count": row["link_count"],
            "attachment_count": row["attachment_count"],
        }
        for key in ("person", "source_system", "source_workspace"):
            if row[key] is not None:
                payload[key] = row[key]
        payload.update({k: v for k, v in extra.items() if v is not None})
        entity = {"entity_type": "note", "entity_id": note_id, **payload}
        hooks.on_event(user_id, event_type, entity, summary)
    except Exception:
        log.exception("Hooks.on_event(%s) failed for note %s", event_type, note_id)


def source_label(row: dict[str, Any]) -> str:
    system = row.get("source_system")
    workspace = row.get("source_workspace")
    if not system:
        return ""
    return f"{system} “{workspace}”" if workspace else str(system)


# ---------------------------------------------------------------------------------------------
# Row -> model
# ---------------------------------------------------------------------------------------------

_NOTE_COLS = (
    "id, user_id, kind, title, body_md, frontmatter, person, note_date, place, origin,"
    " source_system, source_workspace, source_doc_id, source_path, source_url,"
    " source_modified_at, content_hash, last_synced_at, deleted_at, created_via, version,"
    " created_at, updated_at, proposed_at, review_pending"
)

_SUMMARY_COLS = (
    "n.id, n.kind, n.title, n.person, n.note_date, n.origin, n.source_system,"
    " n.source_workspace, n.source_path, n.last_synced_at, n.deleted_at, n.updated_at,"
    " n.created_at, n.review_pending, (n.frontmatter -> 'duration') AS duration"
)

_LIST_ORDER = (
    "COALESCE(n.note_date, to_char(n.created_at, 'YYYY-MM-DD')) DESC,"
    " COALESCE(n.updated_at, n.created_at) DESC, n.id DESC"
)


def _note_row(cfg: HostConfig, user_id: str, note_id: int, *, lock: bool = False) -> dict[str, Any]:
    rows = cfg.db.run(
        f"SELECT {_NOTE_COLS} FROM notes WHERE id = %s AND user_id = %s"
        + (" FOR UPDATE" if lock else ""),
        [note_id, user_id],
    )
    if not rows:
        raise NoteNotFound(f"note {note_id} not found")
    return rows[0]


def _link_model(
    row: dict[str, Any], labeler: Labeler, via: tuple[str, int] | None = None
) -> NoteLink:
    data: dict[str, Any] = {
        "id": row["id"],
        "entity_type": row["entity_type"],
        "entity_id": row["entity_id"],
        "entity_label": labeler.label(row["entity_type"], row["entity_id"]),
        "anchor": row["anchor"],
        "quote": row["quote"],
        "comment": row["comment"],
        "action_item": row["action_item"],
        "action_completed": row["action_completed"] or 0,
        "backlog_id": row["backlog_id"],
        "lane": row["lane"],
        "status": row["status"],
        "proposed_by": row["proposed_by"],
        "confidence": _confidence(row["confidence"]),
        "sort_order": row["sort_order"] or 0,
    }
    if via is not None:
        data["via"] = {"entity_type": via[0], "entity_id": via[1]}
    return NoteLink.model_validate(data)


def _attachment_models(cfg: HostConfig, user_id: str, note_id: int) -> list[Attachment]:
    # Imported here because attachments subclasses NotesError, so it imports this module (C2).
    from arp_notes import attachments

    rows = cfg.db.run(
        "SELECT a.id, a.blob_id, a.filename, a.ref_in_markdown, b.mime, b.size_bytes, b.sha256,"
        " b.width, b.height FROM note_attachments a JOIN blobs b ON b.id = a.blob_id"
        " WHERE a.note_id = %s ORDER BY a.sort_order, a.id",
        [note_id],
    )
    return [
        Attachment.model_validate(
            {**row, "content_url": attachments.content_url(cfg, user_id, row["blob_id"])}
        )
        for row in rows
    ]


def duration_minutes(value: Any) -> int | None:
    """K§2 duration_min: int(frontmatter.duration) when it parses as a whole number."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    if isinstance(value, float):
        return int(value) if value.is_integer() and value >= 0 else None
    if isinstance(value, str):
        text = value.strip()
        return int(text) if text.isascii() and text.isdigit() else None
    return None


def _summaries(
    cfg: HostConfig, user_id: str, rows: Sequence[dict[str, Any]], labeler: Labeler
) -> list[NoteSummary]:
    ids = [row["id"] for row in rows]
    if not ids:
        return []
    links: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for link in cfg.db.run(
        "SELECT id, note_id, entity_type, entity_id, action_item, sort_order FROM note_links"
        " WHERE note_id = ANY(%s) AND status = 'confirmed' ORDER BY sort_order, id",
        [ids],
    ):
        links[link["note_id"]].append(link)
    attachment_counts = {
        r["note_id"]: r["n"]
        for r in cfg.db.run(
            "SELECT note_id, COUNT(*) AS n FROM note_attachments WHERE note_id = ANY(%s)"
            " GROUP BY note_id",
            [ids],
        )
    }
    thumbnails = {
        r["note_id"]: r["blob_id"]
        for r in cfg.db.run(
            "SELECT DISTINCT ON (a.note_id) a.note_id, a.blob_id FROM note_attachments a"
            " JOIN blobs b ON b.id = a.blob_id WHERE a.note_id = ANY(%s) AND b.mime LIKE %s"
            " ORDER BY a.note_id, a.sort_order, a.id",
            [ids, "image/%"],
        )
    }
    out: list[NoteSummary] = []
    for row in rows:
        mine = links.get(row["id"], [])
        ranked = sorted(
            mine,
            key=lambda link: (
                _TOP_LINK_RANK.get(link["entity_type"], 3),
                link["sort_order"] or 0,
                link["id"],
            ),
        )
        top: list[dict[str, Any]] = []
        seen: set[tuple[str, int]] = set()
        for link in ranked:
            key = (link["entity_type"], link["entity_id"])
            if key in seen:
                continue
            seen.add(key)
            top.append(
                {**_pick(link, "entity_type", "entity_id"), "entity_label": labeler.label(*key)}
            )
            if len(top) == TOP_LINKS:
                break
        out.append(
            NoteSummary.model_validate(
                {
                    "id": row["id"],
                    "kind": row["kind"],
                    "title": row["title"],
                    "person": row["person"],
                    "note_date": row["note_date"],
                    "origin": row["origin"],
                    "source_system": row["source_system"],
                    "source_workspace": row["source_workspace"],
                    "source_path": row["source_path"],
                    "last_synced_at": row["last_synced_at"],
                    "deleted_at": row["deleted_at"],
                    "updated_at": row["updated_at"] or row["created_at"],
                    "link_count": len(mine),
                    "attachment_count": attachment_counts.get(row["id"], 0),
                    "top_links": top,
                    "action_count": sum(1 for link in mine if link["action_item"]),
                    "review_pending": row["review_pending"] or 0,
                    "duration_min": duration_minutes(as_json(row["duration"])),
                    # C3 signs this into K§2 `thumbnail_url` (it owns the signer call).
                    "thumbnail_blob_id": thumbnails.get(row["id"]),
                }
            )
        )
    return out


def _pick(row: dict[str, Any], *keys: str) -> dict[str, Any]:
    return {key: row[key] for key in keys}


# ---------------------------------------------------------------------------------------------
# Notes: read
# ---------------------------------------------------------------------------------------------


def get_note(cfg: HostConfig, user_id: str, note_id: int) -> Note:
    """A.2 `GET /notes/{id}`: the note with attachments and links (confirmed and orphaned).

    Rejected links are suppression markers, not content, so they are left out. Raises
    NoteNotFound. Needs `attachments.content_url` (C2) to sign attachment URLs.
    """
    row = _note_row(cfg, user_id, note_id)
    labeler = Labeler(cfg, user_id)
    link_rows = cfg.db.run(
        "SELECT * FROM note_links WHERE note_id = %s AND status IN ('confirmed', 'orphaned')"
        " ORDER BY sort_order, id",
        [note_id],
    )
    return Note.model_validate(
        {
            **row,
            "frontmatter": as_json(row["frontmatter"], {}) or {},
            "created_via": row["created_via"] or "web",
            "version": row["version"] or 1,
            "review_pending": row["review_pending"] or 0,
            "attachments": _attachment_models(cfg, user_id, note_id),
            "links": [_link_model(link, labeler) for link in link_rows],
        }
    )


def _encode_cursor(row: dict[str, Any]) -> str:
    sort_date = row["note_date"] or (row["created_at"].strftime("%Y-%m-%d"))
    stamp = (row["updated_at"] or row["created_at"]).isoformat()
    raw = json.dumps([sort_date, stamp, row["id"]]).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _decode_cursor(cursor: str) -> tuple[str, str, int]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        sort_date, stamp, note_id = json.loads(base64.urlsafe_b64decode(padded))
        datetime.fromisoformat(stamp)
        return str(sort_date), str(stamp), int(note_id)
    except (ValueError, TypeError, binascii.Error) as exc:
        raise InvalidCursor("malformed cursor") from exc


def _like_pattern(q: str) -> str:
    escaped = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def list_notes(
    cfg: HostConfig,
    user_id: str,
    *,
    kind: str | None = None,
    origin: str | None = None,
    source_system: str | None = None,
    q: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = 50,
    before: str | None = None,
    include_deleted: bool = False,
) -> NoteList:
    """A.2 + K§2 `GET /notes`.

    Newest first by note_date (created date when a note has none), then updated_at, then id.
    `before` is the opaque `next_cursor` of the previous page. `sync_sources` is the user's
    imported-source aggregate and ignores the filters and the page.

    NoteSummary.thumbnail_url is left unset: the first image attachment's blob id comes back as
    the extra field `thumbnail_blob_id` for C3 to sign.
    """
    limit = max(1, min(limit, MAX_PAGE))
    where = ["n.user_id = %s"]
    params: list[Any] = [user_id]
    if not include_deleted:
        where.append("n.deleted_at IS NULL")
    for column, value in (("kind", kind), ("origin", origin), ("source_system", source_system)):
        if value:
            where.append(f"n.{column} = %s")
            params.append(value)
    if q:
        where.append("(n.title ILIKE %s OR n.body_md ILIKE %s OR n.person ILIKE %s)")
        params.extend([_like_pattern(q)] * 3)
    if date_from:
        where.append("n.note_date >= %s")
        params.append(date_from)
    if date_to:
        where.append("n.note_date <= %s")
        params.append(date_to)
    if before:
        sort_date, stamp, note_id = _decode_cursor(before)
        where.append(
            "(COALESCE(n.note_date, to_char(n.created_at, 'YYYY-MM-DD')),"
            " COALESCE(n.updated_at, n.created_at), n.id) < (%s, %s::timestamp, %s)"
        )
        params.extend([sort_date, stamp, note_id])
    rows = cfg.db.run(
        f"SELECT {_SUMMARY_COLS} FROM notes n WHERE {' AND '.join(where)}"
        f" ORDER BY {_LIST_ORDER} LIMIT %s",
        [*params, limit + 1],
    )
    page, more = rows[:limit], len(rows) > limit
    items = _summaries(cfg, user_id, page, Labeler(cfg, user_id))
    return NoteList.model_validate(
        {
            "items": items,
            "next_cursor": _encode_cursor(page[-1]) if more else None,
            "sync_sources": _sync_sources(cfg, user_id),
        }
    )


def _sync_sources(cfg: HostConfig, user_id: str) -> list[SyncSource]:
    rows = cfg.db.run(
        "SELECT source_system, source_workspace, MAX(last_synced_at) AS last_synced_at,"
        " COUNT(*) FILTER (WHERE deleted_at IS NULL) AS note_count FROM notes"
        " WHERE user_id = %s AND origin = 'source' AND source_system IS NOT NULL"
        " AND source_workspace IS NOT NULL GROUP BY source_system, source_workspace"
        " ORDER BY MAX(last_synced_at) DESC NULLS LAST, source_system, source_workspace",
        [user_id],
    )
    return [SyncSource.model_validate(row) for row in rows]


def _expand_children(
    cfg: HostConfig, user_id: str, root: tuple[str, int]
) -> dict[tuple[str, int], tuple[str, int]]:
    """Descendants of `root` through `LinkSchemes.children`, as node -> its first-level child.

    A host may return grandchildren itself (PT composer -> repertoire -> movements); the walk
    also recurses, bounded by depth and size, so either style works.
    """
    branch: dict[tuple[str, int], tuple[str, int]] = {}
    frontier: list[tuple[tuple[str, int], tuple[str, int]]] = [(root, root)]
    for depth in range(_MAX_CHILD_DEPTH):
        nxt: list[tuple[tuple[str, int], tuple[str, int]]] = []
        for node, top in frontier:
            scheme = scheme_for(cfg, node[0])
            if not isinstance(scheme, SchemeChildren):
                continue
            for child_type, child_id in scheme.children(user_id, node[0], node[1]):
                child = (str(child_type), int(child_id))
                if child == root or child in branch:
                    continue
                branch[child] = child if depth == 0 else top
                nxt.append((child, branch[child]))
                if len(branch) >= _MAX_CHILD_NODES:
                    return branch
        frontier = nxt
        if not frontier:
            break
    return branch


def by_entity(
    cfg: HostConfig,
    user_id: str,
    entity_type: str,
    entity_id: int,
    *,
    limit: int = 50,
    include_children: bool = False,
) -> EntityNotes:
    """A.2 + K§2 `GET /notes/by-entity/{entity_type}/{entity_id}`.

    Each item is a note and the links that matched. With `include_children` links on a child
    entity (via `LinkSchemes.children`) match too, and each such link carries
    `via = {entity_type, entity_id}`: the direct child of the requested entity it sits under
    (the link's own entity for a direct child; the piece for a movement under a composer).

    Confirmed links match. Orphaned links match only on tombstoned notes, which stay reachable
    from the pieces they cover with `deleted_at` set (ADR §3.2).
    """
    limit = max(1, min(limit, MAX_PAGE))
    root = (entity_type, int(entity_id))
    via = _expand_children(cfg, user_id, root) if include_children else {}
    by_type: dict[str, list[int]] = defaultdict(list)
    for kind, eid in [root, *via]:
        by_type[kind].append(eid)
    clause = " OR ".join("(l.entity_type = %s AND l.entity_id = ANY(%s))" for _ in by_type)
    params: list[Any] = [x for kind, ids in by_type.items() for x in (kind, ids)]
    live = "(l.status = 'confirmed' OR (l.status = 'orphaned' AND n.deleted_at IS NOT NULL))"
    note_rows = cfg.db.run(
        f"SELECT {_SUMMARY_COLS} FROM notes n WHERE n.user_id = %s AND EXISTS ("
        f"SELECT 1 FROM note_links l WHERE l.note_id = n.id AND {live} AND ({clause}))"
        f" ORDER BY {_LIST_ORDER} LIMIT %s",
        [user_id, *params, limit],
    )
    labeler = Labeler(cfg, user_id)
    summaries = _summaries(cfg, user_id, note_rows, labeler)
    ids = [row["id"] for row in note_rows]
    links: dict[int, list[NoteLink]] = defaultdict(list)
    if ids:
        for link in cfg.db.run(
            f"SELECT l.* FROM note_links l JOIN notes n ON n.id = l.note_id"
            f" WHERE l.note_id = ANY(%s) AND {live} AND ({clause}) ORDER BY l.sort_order, l.id",
            [ids, *params],
        ):
            key = (link["entity_type"], link["entity_id"])
            links[link["note_id"]].append(
                _link_model(link, labeler, via.get(key) if key != root else None)
            )
    return EntityNotes(
        items=[EntityNote(note=s, links=links[s.id]) for s in summaries],
    )


# ---------------------------------------------------------------------------------------------
# Notes: write
# ---------------------------------------------------------------------------------------------


# ![name](attachment://<blob_id>) is an image and [name](attachment://<blob_id>) any other file: the
# refs the editor's paste/drop path writes. `pending-…` ids are upload placeholders, not blobs.
_ATTACHMENT_REF = re.compile(r"!?\[([^\]\n]*)\]\(attachment://(\d+)\)")
_CODE = re.compile(r"^(```|~~~).*?(?:^\1[^\n]*$|\Z)|`[^`\n]+`", re.DOTALL | re.MULTILINE)


def body_attachment_refs(body_md: str) -> list[tuple[str, int, str]]:
    """The `attachment://<blob_id>` refs in a body -> [(ref_in_markdown, blob_id, link text)].

    Code (fences and inline spans) is skipped, and a repeated ref counts once, in order.
    """
    if "attachment://" not in body_md:
        return []
    text = _CODE.sub(lambda m: " " * len(m.group(0)), body_md)
    found: dict[str, tuple[str, int, str]] = {}
    for m in _ATTACHMENT_REF.finditer(text):
        ref = body_md[m.start() : m.end()]
        found.setdefault(ref, (ref, int(m.group(2)), body_md[m.start(1) : m.end(1)].strip()))
    return list(found.values())


def reconcile_body_attachments(cfg: HostConfig, user_id: str, note_id: int, body_md: str) -> None:
    """Make an app note's `note_attachments` match the `attachment://<blob_id>` refs in its body.

    The app-note counterpart of the sync reconciler: rows are keyed by `ref_in_markdown`, so a
    row keeps its id while its ref stays in the body, a missing row is inserted (filename = the
    link text) and a row whose ref left the body is deleted. A ref to a blob the user does not
    own, or that does not exist, gets no row and the body is untouched. Call inside the write's
    transaction.
    """
    refs = body_attachment_refs(body_md)
    kept: list[str] = []
    for order, (ref, blob_id, name) in enumerate(refs):
        owned = cfg.db.run(
            "INSERT INTO note_attachments (note_id, blob_id, filename, ref_in_markdown, sort_order)"
            " SELECT %s, b.id, %s, %s, %s FROM blobs b WHERE b.id = %s AND b.user_id = %s"
            " ON CONFLICT (note_id, ref_in_markdown) DO UPDATE SET blob_id = EXCLUDED.blob_id,"
            " filename = EXCLUDED.filename, sort_order = EXCLUDED.sort_order RETURNING id",
            [note_id, name or f"attachment-{blob_id}", ref, order, blob_id, user_id],
        )
        if owned:
            kept.append(ref)
    cfg.db.run(
        "DELETE FROM note_attachments WHERE note_id = %s AND NOT (ref_in_markdown = ANY(%s))",
        [note_id, kept],
    )


def create_note(
    cfg: HostConfig, user_id: str, body: NoteCreate, *, created_via: str = "web"
) -> Note:
    """A.2 `POST /notes`: an app-authored note (origin='app'). Emits `note_created`."""
    with cfg.db.transaction():
        rows = cfg.db.run(
            "INSERT INTO notes (user_id, kind, title, body_md, person, note_date, place, origin,"
            " created_via, version) VALUES (%s, %s, %s, %s, %s, %s, %s, 'app', %s, 1) RETURNING id",
            [
                user_id,
                body.kind or "note",
                body.title,
                body.body_md or "",
                body.person,
                body.note_date,
                body.place,
                created_via,
            ],
        )
        note_id = rows[0]["id"]
        reconcile_body_attachments(cfg, user_id, note_id, body.body_md or "")
    emit_event(cfg, user_id, "note_created", note_id, f"Note created: {body.title}")
    return get_note(cfg, user_id, note_id)


# kind/person/note_date/place are editable on both origins; the rest is the source's.
_ALWAYS_EDITABLE = ("kind", "person", "note_date", "place")
_NOT_NULL = ("kind", "title", "body_md")


def patch_note(cfg: HostConfig, user_id: str, note_id: int, body: NotePatch) -> Note:
    """A.2 `PATCH /notes/{id}`.

    Only fields present in the request change. `person`, `note_date` and `place` can be cleared
    with an explicit null; `kind`, `title` and `body_md` ignore null. For origin='source' a
    title or body edit raises ReadOnlyImport (409). An app note's `version` advances so a
    concurrent autosave sees the conflict.
    """
    sent = body.model_fields_set
    with cfg.db.transaction():
        row = _note_row(cfg, user_id, note_id, lock=True)
        values: dict[str, Any] = {}
        for column in (*_ALWAYS_EDITABLE, "title", "body_md"):
            if column not in sent:
                continue
            value = getattr(body, column)
            if value is None and column in _NOT_NULL:
                continue
            if column not in _ALWAYS_EDITABLE and row["origin"] == "source":
                raise ReadOnlyImport("imported notes are read-only; edit the source")
            values[column] = value
        if values:
            assignments = [f"{column} = %s" for column in values]
            if row["origin"] == "app":
                assignments.append("version = COALESCE(version, 1) + 1")
            assignments.append("updated_at = CURRENT_TIMESTAMP")
            cfg.db.run(
                f"UPDATE notes SET {', '.join(assignments)} WHERE id = %s AND user_id = %s",
                [*values.values(), note_id, user_id],
            )
            if "body_md" in values:
                reconcile_body_attachments(cfg, user_id, note_id, values["body_md"])
    return get_note(cfg, user_id, note_id)


def autosave_note(
    cfg: HostConfig, user_id: str, note_id: int, body: AutosaveBody
) -> AutosaveResult:
    """A.2 `PATCH /notes/{id}/autosave` with the house envelope.

    `{note}` when `body.version` matches the stored version (which then advances), otherwise
    `{conflict: true, server_version, server_data}` and nothing is written. App notes only:
    origin='source' raises ReadOnlyImport.
    """
    with cfg.db.transaction():
        row = _note_row(cfg, user_id, note_id, lock=True)
        if row["origin"] == "source":
            raise ReadOnlyImport("imported notes are read-only; edit the source")
        current = row["version"] or 1
        saved = body.version == current
        if saved:
            cfg.db.run(
                "UPDATE notes SET body_md = %s, version = %s, updated_at = CURRENT_TIMESTAMP"
                " WHERE id = %s AND user_id = %s",
                [body.body_md, current + 1, note_id, user_id],
            )
            reconcile_body_attachments(cfg, user_id, note_id, body.body_md)
    note = get_note(cfg, user_id, note_id)
    if saved:
        return AutosaveResult.model_validate({"note": note})
    return AutosaveResult.model_validate(
        {"conflict": True, "server_version": note.version, "server_data": note}
    )


def delete_note(cfg: HostConfig, user_id: str, note_id: int) -> None:
    """A.2 `DELETE /notes/{id}` (D11): hard delete, cascading links and attachment rows.

    Blobs are untouched (they are refcounted and collected later). Backlog rows the host made
    keep a dangling `source_note_link_id`, like lesson refs today. Raises NoteNotFound.
    """
    deleted = cfg.db.run(
        "DELETE FROM notes WHERE id = %s AND user_id = %s RETURNING id", [note_id, user_id]
    )
    if not deleted:
        raise NoteNotFound(f"note {note_id} not found")


# ---------------------------------------------------------------------------------------------
# Links: confirm
# ---------------------------------------------------------------------------------------------


def _norm_anchor(anchor: str | None) -> str:
    return anchor or ""


def _confirm_one(
    cfg: HostConfig,
    user_id: str,
    note_id: int,
    *,
    entity_type: str,
    entity_id: int,
    anchor: str | None,
    quote: str | None,
    comment: str | None,
    proposed_by: str | None,
    confidence: float | None,
) -> tuple[int, bool]:
    """Confirm one link, updating in place on the dedupe key. -> (link id, newly confirmed)."""
    existing = cfg.db.run(
        "SELECT id, status FROM note_links WHERE note_id = %s AND entity_type = %s"
        " AND entity_id = %s AND COALESCE(anchor, '') = %s",
        [note_id, entity_type, entity_id, _norm_anchor(anchor)],
    )
    if existing:
        link_id = existing[0]["id"]
        cfg.db.run(
            "UPDATE note_links SET status = 'confirmed',"
            " quote = COALESCE(%s, quote), comment = COALESCE(%s, comment),"
            " proposed_by = COALESCE(%s, proposed_by), confidence = COALESCE(%s, confidence),"
            " updated_at = CURRENT_TIMESTAMP WHERE id = %s",
            [quote, comment, proposed_by, confidence, link_id],
        )
        return link_id, existing[0]["status"] != "confirmed"
    rows = cfg.db.run(
        "INSERT INTO note_links (note_id, user_id, entity_type, entity_id, anchor, quote,"
        " comment, status, proposed_by, confidence, sort_order) VALUES"
        " (%s, %s, %s, %s, %s, %s, %s, 'confirmed', %s, %s,"
        "  (SELECT COALESCE(MAX(sort_order), -1) + 1 FROM note_links WHERE note_id = %s))"
        " RETURNING id",
        [
            note_id,
            user_id,
            entity_type,
            entity_id,
            anchor,
            quote,
            comment,
            proposed_by or "user",
            confidence,
            note_id,
        ],
    )
    return rows[0]["id"], True


def _links_at_anchor(cfg: HostConfig, note_id: int, anchor: str | None) -> list[dict[str, Any]]:
    return cfg.db.run(
        "SELECT * FROM note_links WHERE note_id = %s AND status = 'confirmed'"
        " AND COALESCE(anchor, '') = %s ORDER BY sort_order, id",
        [note_id, _norm_anchor(anchor)],
    )


def _flat(text: str) -> str:
    # One action per line in note_links.action_item, so an action cannot hold a newline.
    return " ".join(text.split())


def confirm_links(cfg: HostConfig, user_id: str, note_id: int, body: ConfirmBody) -> ConfirmResult:
    """A.2 `POST /notes/{id}/confirm`, in one transaction.

    - `rejected` persists as status='rejected' so the pair is never re-proposed. It is applied
      first, so an item that is both rejected and confirmed ends up confirmed.
    - `links` confirm on the dedupe key (note, entity, anchor): a repeat updates the row and
      never duplicates it. Counts are of rows that changed state, so a repeat reports 0.
    - `takeaways` become a comment on the first confirmed link at the same anchor (appended as a
      paragraph when it has one) or raise TakeawayNeedsLink.
    - `action_items` attach to `links[link_index]`, else to the link for their own
      entity/anchor (created and confirmed when absent), else to a confirmed link at their
      anchor, else raise ActionNeedsLink. Each new action calls `Hooks.on_action_item`
      and stores the returned backlog id on the link. `action_item` holds one action per line;
      an action already on the link is skipped, which keeps a repeat confirm from duplicating
      backlog rows.
    - `deferred` is only reported (in the `note_enriched` event); R1 owns the review count.
    - `someday` raises SomedayUnsupported unless the policy and `Hooks.on_someday` allow it;
      then `on_someday(user_id, note_id, item)` runs per item (not frozen by the contract yet).

    `ConfirmResult.review_pending` is the stored value. The route overlays
    `review.apply_confirm`'s dict (K§3), which owns the recount.
    """
    hooks = cfg.hooks
    someday = body.someday or []
    if someday and not (cfg.policy.someday and hooks is not None and hooks.on_someday):
        raise SomedayUnsupported("this host does not keep someday ideas")
    links_created = links_rejected = takeaways_created = someday_created = 0
    backlog: list[int] = []
    with cfg.db.transaction():
        note = _note_row(cfg, user_id, note_id, lock=True)

        for rej in body.rejected:
            row = cfg.db.run(
                "SELECT id, status FROM note_links WHERE note_id = %s AND entity_type = %s"
                " AND entity_id = %s AND COALESCE(anchor, '') = %s",
                [note_id, rej.entity_type, rej.entity_id, _norm_anchor(rej.anchor)],
            )
            if not row:
                cfg.db.run(
                    "INSERT INTO note_links (note_id, user_id, entity_type, entity_id, anchor,"
                    " status) VALUES (%s, %s, %s, %s, %s, 'rejected')",
                    [note_id, user_id, rej.entity_type, rej.entity_id, rej.anchor],
                )
                links_rejected += 1
            elif row[0]["status"] != "rejected":
                cfg.db.run(
                    "UPDATE note_links SET status = 'rejected', updated_at = CURRENT_TIMESTAMP"
                    " WHERE id = %s",
                    [row[0]["id"]],
                )
                links_rejected += 1

        link_ids: list[int] = []
        for link in body.links:
            link_id, created = _confirm_one(
                cfg,
                user_id,
                note_id,
                entity_type=link.entity_type,
                entity_id=link.entity_id,
                anchor=link.anchor,
                quote=link.quote,
                comment=link.comment,
                proposed_by=link.proposed_by,
                confidence=link.confidence,
            )
            link_ids.append(link_id)
            links_created += created

        for takeaway in body.takeaways or []:
            targets = _links_at_anchor(cfg, note_id, takeaway.anchor)
            if not targets:
                raise TakeawayNeedsLink(
                    "a takeaway needs a confirmed link at its anchor", anchor=takeaway.anchor
                )
            target = targets[0]
            have = target["comment"] or ""
            if takeaway.comment in have.split("\n\n"):
                continue
            cfg.db.run(
                "UPDATE note_links SET comment = %s, updated_at = CURRENT_TIMESTAMP WHERE id = %s",
                [f"{have}\n\n{takeaway.comment}" if have else takeaway.comment, target["id"]],
            )
            takeaways_created += 1

        # Resolve every action's link before any hook runs, so a bad request writes no backlog.
        planned: list[tuple[int, str, str]] = []
        for action in body.action_items:
            if action.link_index is not None:
                if not 0 <= action.link_index < len(link_ids):
                    raise InvalidLinkIndex(
                        "link_index is outside links", link_index=action.link_index
                    )
                target_id = link_ids[action.link_index]
            elif action.entity_type is not None and action.entity_id is not None:
                target_id, created = _confirm_one(
                    cfg,
                    user_id,
                    note_id,
                    entity_type=action.entity_type,
                    entity_id=action.entity_id,
                    anchor=action.anchor,
                    quote=None,
                    comment=None,
                    proposed_by=None,
                    confidence=None,
                )
                links_created += created
            else:
                targets = _links_at_anchor(cfg, note_id, action.anchor)
                if not targets:
                    raise ActionNeedsLink(
                        "an action item needs a link_index, an entity or a confirmed link at"
                        " its anchor",
                        anchor=action.anchor,
                    )
                target_id = targets[0]["id"]
            planned.append((target_id, _flat(action.text), action.lane))

        for target_id, text, lane in planned:
            row = cfg.db.run("SELECT * FROM note_links WHERE id = %s", [target_id])[0]
            lines = [line for line in (row["action_item"] or "").split("\n") if line]
            if text in lines:
                continue
            backlog_id = row["backlog_id"]
            if hooks is not None and hooks.on_action_item is not None:
                backlog_id = hooks.on_action_item(
                    user_id, {**row, "action_item": text, "note_title": note["title"]}, lane
                )
                backlog.append(backlog_id)
            cfg.db.run(
                "UPDATE note_links SET action_item = %s, backlog_id = %s, lane = %s,"
                " updated_at = CURRENT_TIMESTAMP WHERE id = %s",
                ["\n".join([*lines, text]), backlog_id, lane, target_id],
            )

        if someday and hooks is not None and hooks.on_someday is not None:
            for item in someday:
                hooks.on_someday(user_id, note_id, item.model_dump(exclude_none=True))
                someday_created += 1

        review_pending = _note_row(cfg, user_id, note_id)["review_pending"] or 0

    deferred = len(body.deferred or [])
    if links_created or links_rejected or backlog or takeaways_created or deferred:
        emit_event(
            cfg,
            user_id,
            "note_enriched",
            note_id,
            f"Links confirmed: {note['title']}",
            links_created=links_created,
            backlog_created=len(backlog),
            rejected=links_rejected,
            deferred=deferred,
        )
    return ConfirmResult(
        links_created=links_created,
        links_rejected=links_rejected,
        backlog_created=backlog,
        takeaways_created=takeaways_created,
        someday_created=someday_created,
        review_pending=review_pending,
    )


# ---------------------------------------------------------------------------------------------
# Blobs and upload tickets (plain row access; the logic lives in attachments.py, C2)
# ---------------------------------------------------------------------------------------------


def find_blob_ids(cfg: HostConfig, user_id: str, sha256s: Iterable[str]) -> dict[str, int]:
    """sha256 -> blobs.id for the hashes this user already has bytes for."""
    wanted = list(dict.fromkeys(sha256s))
    if not wanted:
        return {}
    rows = cfg.db.run(
        "SELECT sha256, id FROM blobs WHERE user_id = %s AND sha256 = ANY(%s)", [user_id, wanted]
    )
    return {row["sha256"]: row["id"] for row in rows}


def get_blob(cfg: HostConfig, user_id: str, blob_id: int) -> dict[str, Any] | None:
    rows = cfg.db.run("SELECT * FROM blobs WHERE id = %s AND user_id = %s", [blob_id, user_id])
    return rows[0] if rows else None


def get_blob_by_sha256(cfg: HostConfig, user_id: str, sha256: str) -> dict[str, Any] | None:
    rows = cfg.db.run("SELECT * FROM blobs WHERE user_id = %s AND sha256 = %s", [user_id, sha256])
    return rows[0] if rows else None


def insert_blob(
    cfg: HostConfig,
    user_id: str,
    *,
    sha256: str,
    mime: str,
    size_bytes: int,
    storage_path: str,
    width: int | None = None,
    height: int | None = None,
) -> dict[str, Any]:
    """Register a blob, idempotent on (user_id, sha256): an existing row is returned unchanged."""
    rows = cfg.db.run(
        "INSERT INTO blobs (user_id, sha256, mime, size_bytes, storage_path, width, height)"
        " VALUES (%s, %s, %s, %s, %s, %s, %s) ON CONFLICT (user_id, sha256) DO NOTHING"
        " RETURNING *",
        [user_id, sha256, mime, size_bytes, storage_path, width, height],
    )
    return rows[0] if rows else get_blob_by_sha256(cfg, user_id, sha256) or {}


def create_ticket(
    cfg: HostConfig,
    user_id: str,
    *,
    token_hash: str,
    sha256: str,
    mime: str,
    size_bytes: int,
    filename: str | None,
    expires_at: datetime,
) -> dict[str, Any]:
    return cfg.db.run(
        "INSERT INTO upload_tickets (user_id, token_hash, sha256, mime, size_bytes, filename,"
        " expires_at) VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING *",
        [user_id, token_hash, sha256, mime, size_bytes, filename, expires_at],
    )[0]


def get_ticket(cfg: HostConfig, token_hash: str) -> dict[str, Any] | None:
    """Look a ticket up by its hashed token. No user: the public PUT route has only the token."""
    rows = cfg.db.run("SELECT * FROM upload_tickets WHERE token_hash = %s", [token_hash])
    return rows[0] if rows else None


def consume_ticket(cfg: HostConfig, ticket_id: int) -> bool:
    """Mark a ticket used. True for exactly one caller, even when two race."""
    return bool(
        cfg.db.run(
            "UPDATE upload_tickets SET consumed_at = CURRENT_TIMESTAMP"
            " WHERE id = %s AND consumed_at IS NULL RETURNING id",
            [ticket_id],
        )
    )
