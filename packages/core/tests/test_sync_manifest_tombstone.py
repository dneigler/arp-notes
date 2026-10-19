"""sync.manifest and sync.tombstone (C1b, ga-mxal.8)."""

from __future__ import annotations

from typing import Any

import pytest
from arp_notes import repo, sync
from arp_notes.config import HostConfig
from arp_notes.models import NoteCreate
from arp_notes.testing.fakedb import FakeDb
from repo_support import (
    OTHER,
    USER,
    FakeHooks,
    add_blob,
    add_link,
    attachment_ref,
    sha,
    upsert_body,
)

pytestmark = pytest.mark.usefixtures("signed_urls")


def put(cfg: HostConfig, doc_id: str, **kw: Any) -> int:
    return sync.upsert(cfg, USER, upsert_body(doc_id, **kw)).note_id


# --- manifest ---------------------------------------------------------------------------------


def test_manifest_lists_one_workspace_with_hashes_and_attachment_shas(
    notes_cfg: HostConfig, notes_db: FakeDb
) -> None:
    _, a = add_blob(notes_db, text="a")
    _, b = add_blob(notes_db, text="b")
    put(
        notes_cfg,
        "d1",
        body_md="v1",
        attachments=[
            attachment_ref(b, "![[b.webp]]"),
            attachment_ref(a, "![[a.webp]]"),
            attachment_ref(b, "![[b2.webp]]"),  # the same bytes under another name
        ],
    )
    put(notes_cfg, "d2")
    sync.upsert(notes_cfg, USER, upsert_body("x", source_workspace="Elsewhere"))
    sync.upsert(notes_cfg, OTHER, upsert_body("y"))

    page = sync.manifest(notes_cfg, USER, "obsidian", "Vault")
    assert page.protocol == 1 and page.next_after is None
    assert [r.source_doc_id for r in page.items] == ["d1", "d2"]
    first, second = page.items
    assert (first.source_path, first.content_hash) == ("d1.md", sha("v1"))
    assert first.attachments == [b, a]  # in note order, each sha once
    assert second.attachments == []
    assert first.last_synced_at and first.deleted_at is None
    assert sync.manifest(notes_cfg, USER, "obsidian", "Nope").items == []
    assert sync.manifest(notes_cfg, USER, "notion", "Vault").items == []


def test_manifest_pages_by_source_doc_id(notes_cfg: HostConfig) -> None:
    for doc_id in ("a", "b", "c", "d", "e"):
        put(notes_cfg, doc_id)
    seen: list[str] = []
    after = None
    pages = 0
    while True:
        page = sync.manifest(notes_cfg, USER, "obsidian", "Vault", limit=2, after=after)
        seen += [r.source_doc_id for r in page.items]
        pages += 1
        after = page.next_after
        if after is None:
            break
    assert (seen, pages) == (["a", "b", "c", "d", "e"], 3)
    page = sync.manifest(notes_cfg, USER, "obsidian", "Vault", limit=2, after="b")
    assert [r.source_doc_id for r in page.items] == ["c", "d"] and page.next_after == "d"
    assert sync.manifest(notes_cfg, USER, "obsidian", "Vault", after="e").items == []


def test_manifest_clamps_the_limit(notes_cfg: HostConfig) -> None:
    for doc_id in ("a", "b"):
        put(notes_cfg, doc_id)
    assert len(sync.manifest(notes_cfg, USER, "obsidian", "Vault", limit=0).items) == 1
    assert len(sync.manifest(notes_cfg, USER, "obsidian", "Vault", limit=10_000).items) == 2
    assert sync.MAX_MANIFEST_PAGE == 500


def test_manifest_includes_tombstones_and_skips_app_notes(
    notes_cfg: HostConfig, notes_db: FakeDb
) -> None:
    put(notes_cfg, "alive")
    put(notes_cfg, "dead")
    sync.tombstone(notes_cfg, USER, "obsidian", "Vault", ["dead"])
    repo.create_note(notes_cfg, USER, NoteCreate(title="mine"))
    rows = {r.source_doc_id: r for r in sync.manifest(notes_cfg, USER, "obsidian", "Vault").items}
    assert set(rows) == {"alive", "dead"}
    assert rows["dead"].deleted_at is not None and rows["alive"].deleted_at is None


# --- tombstone --------------------------------------------------------------------------------


def test_tombstone_keeps_the_note_and_orphans_its_links(
    notes_cfg: HostConfig, notes_db: FakeDb, fake_hooks: FakeHooks
) -> None:
    note_id = put(notes_cfg, "d1")
    other = put(notes_cfg, "d2")
    notes_db.run("UPDATE notes SET review_pending = 5")
    add_link(notes_db, note_id, "repertoire", 35, anchor="intro")
    add_link(notes_db, note_id, "composer", 1, status="rejected")
    add_link(notes_db, other, "repertoire", 35, anchor="intro")
    fake_hooks.events.clear()

    result = sync.tombstone(notes_cfg, USER, "obsidian", "Vault", ["d1", "ghost"])
    assert result.model_dump() == {"tombstoned": 1, "unknown": ["ghost"]}

    row = notes_db.run("SELECT * FROM notes WHERE id = %s", [note_id])[0]
    assert row["deleted_at"] is not None and row["review_pending"] == 0
    assert row["body_md"] == "# Intro\n\ntext\n"  # the body stays
    links = notes_db.run("SELECT status FROM note_links WHERE note_id = %s ORDER BY id", [note_id])
    assert [r["status"] for r in links] == ["orphaned", "rejected"]
    untouched = notes_db.run("SELECT review_pending FROM notes WHERE id = %s", [other])[0]
    assert untouched["review_pending"] == 5
    assert notes_db.run("SELECT status FROM note_links WHERE note_id = %s", [other]) == [
        {"status": "confirmed"}
    ]

    [(_, event, entity, _)] = fake_hooks.events
    assert (event, entity["note_id"], entity["origin"]) == ("note_tombstoned", note_id, "source")
    # Gone from the list unless asked for, still readable.
    assert [i.id for i in repo.list_notes(notes_cfg, USER).items] == [other]
    assert repo.get_note(notes_cfg, USER, note_id).deleted_at is not None


def test_tombstone_is_idempotent_and_scoped(
    notes_cfg: HostConfig, notes_db: FakeDb, fake_hooks: FakeHooks
) -> None:
    put(notes_cfg, "d1")
    sync.upsert(notes_cfg, OTHER, upsert_body("d1"))
    assert sync.tombstone(notes_cfg, USER, "obsidian", "Vault", ["d1"]).tombstoned == 1
    again = sync.tombstone(notes_cfg, USER, "obsidian", "Vault", ["d1", "d1"])
    assert (again.tombstoned, again.unknown) == (0, [])
    assert fake_hooks.names().count("note_tombstoned") == 1
    # The same id in another workspace, system or user is a different note.
    wrong = sync.tombstone(notes_cfg, USER, "obsidian", "Other", ["d1"])
    assert (wrong.tombstoned, wrong.unknown) == (0, ["d1"])
    theirs = notes_db.run("SELECT deleted_at FROM notes WHERE user_id = %s", [OTHER])
    assert theirs == [{"deleted_at": None}]


def test_tombstone_with_nothing_to_do(notes_cfg: HostConfig) -> None:
    assert sync.tombstone(notes_cfg, USER, "obsidian", "Vault", []).model_dump() == {
        "tombstoned": 0,
        "unknown": [],
    }


def test_a_tombstoned_note_comes_back_when_its_file_does(
    notes_cfg: HostConfig, notes_db: FakeDb, fake_hooks: FakeHooks
) -> None:
    note_id = put(notes_cfg, "d1")
    add_link(notes_db, note_id, "repertoire", 35, anchor="intro")
    add_link(notes_db, note_id, "composer", 1)  # whole note
    sync.tombstone(notes_cfg, USER, "obsidian", "Vault", ["d1"])
    fake_hooks.events.clear()

    # The very same bytes: still "updated", because the note's state changed.
    result = sync.upsert(notes_cfg, USER, upsert_body("d1"))
    assert (result.outcome, result.note_id, result.links_orphaned) == ("updated", note_id, 0)
    row = notes_db.run("SELECT deleted_at FROM notes WHERE id = %s", [note_id])[0]
    assert row["deleted_at"] is None
    statuses = notes_db.run("SELECT status FROM note_links WHERE note_id = %s", [note_id])
    assert {r["status"] for r in statuses} == {"confirmed"}
    assert fake_hooks.names() == ["note_synced"]
    assert [i.id for i in repo.list_notes(notes_cfg, USER).items] == [note_id]


def test_a_tombstoned_note_returns_with_a_rewritten_body(
    notes_cfg: HostConfig, notes_db: FakeDb
) -> None:
    note_id = put(notes_cfg, "d1")
    add_link(notes_db, note_id, "repertoire", 35, anchor="intro")
    add_link(notes_db, note_id, "repertoire", 36, anchor="gone")
    sync.tombstone(notes_cfg, USER, "obsidian", "Vault", ["d1"])
    sync.upsert(notes_cfg, USER, upsert_body("d1", "# Intro\n"))
    rows = notes_db.run(
        "SELECT anchor, status FROM note_links WHERE note_id = %s ORDER BY id", [note_id]
    )
    assert [(r["anchor"], r["status"]) for r in rows] == [
        ("intro", "confirmed"),
        ("gone", "orphaned"),
    ]
