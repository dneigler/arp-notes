"""Markdown + attachments export (ADR §3.7, A.2 `GET /notes/{id}/export`). Owner: C3 (ga-mxal.10).

`export_note` returns the note as one Markdown document and the manifest of its attachments.

- An app-authored note (origin='app') gets a frontmatter block: `arp_id`, `kind`, `person`,
  `note_date`, `place`, `exported_at` (empty ones left out). When the body already opens with a
  frontmatter block the keys go inside it, never in a second block.
- An imported note (origin='source') is exported verbatim: its stored body already is the source
  file, `arp_id` included (D1). Nothing is added unless the caller asks for enrichment.
- `with_enrichment` is opt-in, so a pull never rewrites a user's frontmatter by surprise. Style
  'frontmatter' adds `arp_links`, `arp_takeaways` and `arp_actions` properties to the note. Style
  'companion' leaves the note alone and returns the `<name>.arp.md` companion document instead
  (the same properties under an `arp_companion_for` header), so a pull makes two requests.
- Keys already present in a frontmatter block are never duplicated or overwritten.

The manifest lists one `Attachment` per embed (A.2 shape, `content_url` signed and relative to the
router mount; the router prefixes it). Embeds in the body are left as stored: rewriting them to
relative paths is the pull command's job.
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from arp_notes import repo
from arp_notes.config import HostConfig
from arp_notes.models import Note, NoteLink

__all__ = ["ExportDisabled", "InvalidEnrichmentStyle", "export_note"]

EnrichmentStyle = Literal["frontmatter", "companion"]
STYLES = ("frontmatter", "companion")

# An arp_id for a note that has no source identity: stable across exports, never reveals the user.
_ARP_NAMESPACE = uuid.UUID("2f1f2f0e-6b8c-5a52-9f4e-3a0f6a5e7d11")

_FRONTMATTER_OPEN = re.compile(r"\A---[ \t]*\r?\n")
_FRONTMATTER_CLOSE = re.compile(r"^(?:---|\.\.\.)[ \t]*\r?$")
_PLAIN = re.compile(r"[A-Za-z][A-Za-z0-9_-]*")
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
# YAML 1.1 words a plain scalar would be read as something else, so they are quoted.
_RESERVED = frozenset({"true", "false", "yes", "no", "on", "off", "null", "y", "n", "~"})


class ExportDisabled(repo.NotesError):
    """Policy.export is off (a genuinely private deployment, ADR §3.7)."""

    status = 403
    code = "export_disabled"


class InvalidEnrichmentStyle(repo.NotesError):
    status = 422
    code = "invalid_enrichment_style"


def _now() -> datetime:
    return datetime.now(UTC)


# ---------------------------------------------------------------------------------------------
# A small YAML writer: just the shapes the export needs, no dependency
# ---------------------------------------------------------------------------------------------


def _scalar(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return str(value)
    text = str(value)
    if _PLAIN.fullmatch(text) and text.casefold() not in _RESERVED:
        return text
    # JSON strings are valid YAML double-quoted scalars, so quoting is one call.
    return json.dumps(text, ensure_ascii=False)


def _list_lines(key: str, rows: list[list[tuple[str, Any]]]) -> list[str]:
    if not rows:
        return [f"{key}: []"]
    lines = [f"{key}:"]
    for row in rows:
        present = [(k, v) for k, v in row if v is not None]
        for i, (name, value) in enumerate(present):
            lines.append(f"  {'- ' if i == 0 else '  '}{name}: {_scalar(value)}")
    return lines


# ---------------------------------------------------------------------------------------------
# Frontmatter surgery (the CLI's rule from D1: insert lines, never re-serialise the user's YAML)
# ---------------------------------------------------------------------------------------------


def _split_frontmatter(body: str) -> tuple[list[str], str, str] | None:
    """-> (block lines between the fences, newline style, text after the closing fence)."""
    opened = _FRONTMATTER_OPEN.match(body)
    if not opened:
        return None
    newline = "\r\n" if opened.group().endswith("\r\n") else "\n"
    lines = body[opened.end() :].splitlines(keepends=True)
    for i, line in enumerate(lines):
        if _FRONTMATTER_CLOSE.match(line.rstrip("\n")):
            return [x.rstrip("\r\n") for x in lines[:i]], newline, "".join(lines[i:])
    return None  # no closing fence: not a frontmatter block


def _top_level_keys(lines: list[str]) -> set[str]:
    keys: set[str] = set()
    for line in lines:
        match = re.match(r"([^\s#:][^:]*?)\s*:(?:\s|$)", line)
        if match:
            keys.add(match.group(1).strip("'\""))
    return keys


def _inject(body: str, entries: list[tuple[str, list[str]]]) -> str:
    """Add `entries` ((key, lines) pairs) to the body's frontmatter, creating the block if absent.

    Entries whose key the block already has are skipped.
    """
    split = _split_frontmatter(body)
    if split is None:
        lines = [line for _, block in entries for line in block]
        return "---\n" + "\n".join(lines) + "\n---\n" + body if lines else body
    present, newline, rest = split
    have = _top_level_keys(present)
    add = [line for key, block in entries if key not in have for line in block]
    if not add:
        return body
    head = _FRONTMATTER_OPEN.match(body)
    assert head is not None
    return head.group() + newline.join([*add, *present]) + newline + rest


# ---------------------------------------------------------------------------------------------
# Building blocks
# ---------------------------------------------------------------------------------------------


def arp_id(note: Note) -> str:
    """The note's id in files: its source id when it has one, else a stable derived UUID."""
    if note.source_doc_id:
        return note.source_doc_id
    return str(uuid.uuid5(_ARP_NAMESPACE, f"{note.user_id}:{note.id}"))


# Values written bare so a reader types them: Obsidian shows a date as a date, and the CLI's
# own `arp_id: <uuid>` line (D1) has no quotes.
_BARE = {
    "arp_id": re.compile(r"[0-9A-Fa-f]{8}(?:-[0-9A-Fa-f]{4}){3}-[0-9A-Fa-f]{12}"),
    "note_date": _DATE,
    "exported_at": re.compile(_DATE.pattern + r"T\d\d:\d\d:\d\dZ"),
}


def _property(key: str, value: Any) -> tuple[str, list[str]] | None:
    """One top-level `key: value` property, or None when the value is empty."""
    if value is None or value == "":
        return None
    bare = _BARE.get(key)
    text = str(value) if bare is not None and bare.fullmatch(str(value)) else _scalar(value)
    return key, [f"{key}: {text}"]


def _header_entries(note: Note, exported_at: str) -> list[tuple[str, list[str]]]:
    fields: list[tuple[str, Any]] = [
        ("arp_id", arp_id(note)),
        ("kind", note.kind),
        ("person", note.person),
        ("note_date", note.note_date),
        ("place", note.place),
        ("exported_at", exported_at),
    ]
    return [entry for key, value in fields if (entry := _property(key, value)) is not None]


def _confirmed(note: Note) -> list[NoteLink]:
    return [link for link in note.links if link.status == "confirmed"]


def _enrichment_entries(note: Note) -> list[tuple[str, list[str]]]:
    """arp_links / arp_takeaways / arp_actions from the confirmed links (ADR §3.7)."""
    links = _confirmed(note)
    arp_links = [
        [
            ("entity_type", link.entity_type),
            ("entity_id", link.entity_id),
            ("entity_label", link.entity_label),
            ("anchor", link.anchor),
            ("quote", link.quote),
            ("confidence", link.confidence),
        ]
        for link in links
    ]
    takeaways = [
        [("anchor", link.anchor), ("comment", link.comment)] for link in links if link.comment
    ]
    actions = [
        [
            ("text", text),
            ("anchor", link.anchor),
            ("entity_type", link.entity_type),
            ("entity_id", link.entity_id),
            ("completed", bool(link.action_completed)),
        ]
        for link in links
        if link.action_item
        for text in link.action_item.splitlines()
        if text.strip()
    ]
    return [
        ("arp_links", _list_lines("arp_links", arp_links)),
        ("arp_takeaways", _list_lines("arp_takeaways", takeaways)),
        ("arp_actions", _list_lines("arp_actions", actions)),
    ]


def _companion(note: Note, exported_at: str) -> str:
    head = [
        _property("arp_id", arp_id(note)),
        _property("arp_companion_for", note.title),
        _property("exported_at", exported_at),
    ]
    lines = [line for entry in head if entry for line in entry[1]]
    lines += [line for _, block in _enrichment_entries(note) for line in block]
    return "---\n" + "\n".join(lines) + "\n---\n"


def _manifest(note: Note) -> list[dict[str, Any]]:
    return [att.model_dump(mode="json", exclude_none=True) for att in note.attachments]


# ---------------------------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------------------------


def export_note(
    cfg: HostConfig,
    user_id: str,
    note_id: int,
    with_enrichment: bool = False,
    style: str = "frontmatter",
) -> tuple[str, list[dict[str, Any]]]:
    """-> (markdown, attachment manifest). style: 'frontmatter' | 'companion'.

    Raises ExportDisabled (403) when the host turned export off, NoteNotFound (404) for a note
    that is not this user's, and InvalidEnrichmentStyle (422) for any other style. With
    `style='companion'` and `with_enrichment` the markdown is the companion document and not the
    note (see the module docstring).
    """
    if not cfg.policy.export:
        raise ExportDisabled("this app does not allow exporting notes")
    if style not in STYLES:
        raise InvalidEnrichmentStyle(f"enrichment_style must be one of {', '.join(STYLES)}")
    note = repo.get_note(cfg, user_id, note_id)
    exported_at = _now().strftime("%Y-%m-%dT%H:%M:%SZ")
    manifest = _manifest(note)

    if with_enrichment and style == "companion":
        return _companion(note, exported_at), manifest

    entries: list[tuple[str, list[str]]] = []
    if note.origin == "app":
        entries += _header_entries(note, exported_at)
    if with_enrichment:
        entries += _enrichment_entries(note)
    return (_inject(note.body_md, entries) if entries else note.body_md), manifest
