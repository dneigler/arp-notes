"""repo: notes CRUD, list/summary fields (K§2), patch/autosave/delete (C1b, ga-mxal.8)."""

from __future__ import annotations

import json
from typing import Any

import pytest
from arp_notes import repo
from arp_notes.config import HostConfig
from arp_notes.models import AutosaveBody, NoteCreate, NotePatch
from arp_notes.testing.fakedb import FakeDb
from repo_support import (
    OTHER,
    USER,
    FakeHooks,
    add_blob,
    add_link,
    add_note,
)

pytestmark = pytest.mark.usefixtures("signed_urls")


def attach(db: FakeDb, note_id: int, blob_id: int, ref: str, order: int = 0) -> None:
    db.run(
        "INSERT INTO note_attachments (note_id, blob_id, filename, ref_in_markdown, sort_order)"
        " VALUES (%s, %s, %s, %s, %s)",
        [note_id, blob_id, ref, ref, order],
    )


# --- create / get ----------------------------------------------------------------------------


def test_create_makes_an_app_note_and_emits_note_created(
    notes_cfg: HostConfig, fake_hooks: FakeHooks
) -> None:
    note = repo.create_note(
        notes_cfg,
        USER,
        NoteCreate(title="Howat", body_md="# Hi", person="Roy", kind="masterclass"),
        created_via="mcp",
    )
    assert (note.origin, note.version, note.created_via) == ("app", 1, "mcp")
    assert (note.kind, note.person, note.body_md) == ("masterclass", "Roy", "# Hi")
    assert note.attachments == [] and note.links == [] and note.review_pending == 0

    [(user, event, entity, summary)] = fake_hooks.events
    assert (user, event) == (USER, "note_created")
    assert entity == {
        "entity_type": "note",
        "entity_id": note.id,
        "event": "note_created",
        "note_id": note.id,
        "note_title": "Howat",
        "kind": "masterclass",
        "person": "Roy",
        "origin": "app",
        "link_count": 0,
        "attachment_count": 0,
    }
    assert "Howat" in summary


def test_create_defaults(notes_cfg: HostConfig) -> None:
    note = repo.create_note(notes_cfg, USER, NoteCreate(title="Bare"))
    assert (note.kind, note.body_md, note.created_via, note.frontmatter) == ("note", "", "web", {})


def test_a_failing_event_hook_never_breaks_the_write(
    notes_cfg: HostConfig, fake_hooks: FakeHooks
) -> None:
    def boom(*_args: object) -> None:
        raise RuntimeError("activity log down")

    fake_hooks.on_event = boom
    assert repo.create_note(notes_cfg, USER, NoteCreate(title="x")).id > 0


def test_get_is_scoped_to_the_user_and_404s(notes_cfg: HostConfig, notes_db: FakeDb) -> None:
    mine = add_note(notes_db)
    theirs = add_note(notes_db, OTHER)
    assert repo.get_note(notes_cfg, USER, mine).id == mine
    for note_id in (theirs, 9999):
        with pytest.raises(repo.NoteNotFound) as err:
            repo.get_note(notes_cfg, USER, note_id)
        assert err.value.status == 404


def test_get_returns_attachments_and_labelled_links(
    notes_cfg: HostConfig, notes_db: FakeDb
) -> None:
    note_id = add_note(notes_db, frontmatter=json.dumps({"duration": 25}))
    blob_id, digest = add_blob(notes_db, text="shot")
    attach(notes_db, note_id, blob_id, "![[shot.webp]]")
    add_link(notes_db, note_id, "repertoire", 35, anchor="etude-3", confidence=0.8, quote="q")
    add_link(notes_db, note_id, "movement", 999, status="orphaned")  # the scheme can't resolve it
    add_link(notes_db, note_id, "composer", 1, status="rejected")

    note = repo.get_note(notes_cfg, USER, note_id)
    assert note.frontmatter == {"duration": 25}
    [att] = note.attachments
    assert (att.sha256, att.blob_id, att.mime) == (digest, blob_id, "image/webp")
    assert att.content_url == f"/attachments/{blob_id}/content?sig=test"
    by_type = {link.entity_type: link for link in note.links}
    assert set(by_type) == {"repertoire", "movement"}  # the rejected one is not content
    assert by_type["repertoire"].entity_label == "Études, Op.10"
    assert by_type["repertoire"].confidence == 0.8
    assert by_type["movement"].entity_label == "movement #999"
    assert by_type["movement"].status == "orphaned"


def test_a_broken_scheme_falls_back_to_a_label(notes_cfg: HostConfig, notes_db: FakeDb) -> None:
    def boom(*_args: object) -> None:
        raise RuntimeError("host down")

    notes_cfg.schemes[0].resolve = boom  # type: ignore[method-assign,assignment]
    note_id = add_note(notes_db)
    add_link(notes_db, note_id, "repertoire", 35)
    assert repo.get_note(notes_cfg, USER, note_id).links[0].entity_label == "repertoire #35"


# --- list: summary fields (K§2) ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (25, 25),
        ("25", 25),
        (" 40 ", 40),
        (25.0, 25),
        (25.5, None),
        ("25 min", None),
        ("", None),
        (True, None),
        (-5, None),
        ("-5", None),
        (None, None),
        ([25], None),
    ],
)
def test_duration_minutes(value: object, expected: int | None) -> None:
    assert repo.duration_minutes(value) == expected


def test_list_summary_carries_the_k2_fields(notes_cfg: HostConfig, notes_db: FakeDb) -> None:
    note_id = add_note(
        notes_db,
        origin="source",
        source_system="obsidian",
        source_workspace="Dave2025",
        source_path="One on one meetings/Howat.md",
        frontmatter=json.dumps({"duration": "25"}),
        review_pending=3,
        note_date="2026-10-18",
    )
    pdf, _ = add_blob(notes_db, text="pdf", mime="application/pdf")
    first_img, _ = add_blob(notes_db, text="one")
    second_img, _ = add_blob(notes_db, text="two")
    attach(notes_db, note_id, pdf, "![[a.pdf]]", 0)
    attach(notes_db, note_id, second_img, "![[2.webp]]", 2)
    attach(notes_db, note_id, first_img, "![[1.webp]]", 1)
    # Inserted in the "wrong" order on purpose: composer first, a duplicate entity, five links.
    add_link(notes_db, note_id, "composer", 1, sort_order=0)
    add_link(notes_db, note_id, "movement", 12, sort_order=1, action_item="slow it down")
    add_link(notes_db, note_id, "repertoire", 35, sort_order=2, anchor="a")
    add_link(notes_db, note_id, "repertoire", 35, sort_order=3, anchor="b")  # same piece again
    add_link(notes_db, note_id, "technique", 7, sort_order=4, action_item="legato drills")
    add_link(notes_db, note_id, "movement", 3, sort_order=5, status="rejected")

    [item] = repo.list_notes(notes_cfg, USER).items
    assert item.id == note_id
    assert (item.source_workspace, item.source_path) == (
        "Dave2025",
        "One on one meetings/Howat.md",
    )
    assert item.duration_min == 25
    assert item.review_pending == 3
    assert (item.link_count, item.action_count, item.attachment_count) == (5, 2, 3)
    assert [(t.entity_type, t.entity_id) for t in item.top_links] == [
        ("repertoire", 35),
        ("movement", 12),
        ("composer", 1),
        ("technique", 7),
    ]
    assert item.top_links[0].entity_label == "Études, Op.10"
    assert item.thumbnail_url is None
    assert item.model_extra == {"thumbnail_blob_id": first_img}


def test_top_links_stop_at_four(notes_cfg: HostConfig, notes_db: FakeDb) -> None:
    note_id = add_note(notes_db)
    for entity_id in range(1, 7):
        add_link(notes_db, note_id, "repertoire", entity_id, sort_order=entity_id)
    [item] = repo.list_notes(notes_cfg, USER).items
    assert item.link_count == 6
    assert [t.entity_id for t in item.top_links] == [1, 2, 3, 4]


def test_a_note_with_nothing_has_empty_summary_fields(
    notes_cfg: HostConfig, notes_db: FakeDb
) -> None:
    add_note(notes_db)
    [item] = repo.list_notes(notes_cfg, USER).items
    assert (item.link_count, item.action_count, item.attachment_count) == (0, 0, 0)
    assert item.top_links == [] and item.duration_min is None
    assert item.model_extra == {"thumbnail_blob_id": None}


# --- list: filters, paging, deleted, sync_sources ---------------------------------------------


def titles(cfg: HostConfig, **kw: object) -> list[str]:
    return [i.title for i in repo.list_notes(cfg, USER, **kw).items]  # type: ignore[arg-type]


def test_list_filters(notes_cfg: HostConfig, notes_db: FakeDb) -> None:
    add_note(notes_db, title="Bach", kind="lecture", note_date="2026-01-05", body_md="fugue")
    add_note(
        notes_db,
        title="Howat",
        kind="masterclass",
        note_date="2026-03-01",
        origin="source",
        source_system="obsidian",
        person="Roy 100%_real",
    )
    add_note(notes_db, OTHER, title="Other user")

    assert titles(notes_cfg) == ["Howat", "Bach"]
    assert titles(notes_cfg, kind="lecture") == ["Bach"]
    assert titles(notes_cfg, origin="source") == ["Howat"]
    assert titles(notes_cfg, source_system="obsidian") == ["Howat"]
    assert titles(notes_cfg, q="FUGUE") == ["Bach"]
    assert titles(notes_cfg, q="roy") == ["Howat"]
    assert titles(notes_cfg, q="100%_real") == ["Howat"]
    assert titles(notes_cfg, q="%") == ["Howat"]  # a literal percent sign, not a wildcard
    assert titles(notes_cfg, q="zzz") == []
    assert titles(notes_cfg, date_from="2026-02-01") == ["Howat"]
    assert titles(notes_cfg, date_to="2026-02-01") == ["Bach"]
    assert titles(notes_cfg, date_from="2026-01-05", date_to="2026-03-01") == ["Howat", "Bach"]


def test_list_pages_newest_first_with_a_cursor(notes_cfg: HostConfig, notes_db: FakeDb) -> None:
    for day in range(1, 6):
        add_note(notes_db, title=f"n{day}", note_date=f"2026-01-0{day}")
    add_note(notes_db, title="undated")  # sorts by its created date: today, so first

    first = repo.list_notes(notes_cfg, USER, limit=4)
    assert [i.title for i in first.items] == ["undated", "n5", "n4", "n3"]
    assert first.next_cursor
    second = repo.list_notes(notes_cfg, USER, limit=4, before=first.next_cursor)
    assert [i.title for i in second.items] == ["n2", "n1"]
    assert second.next_cursor is None


def test_list_cursor_is_stable_across_ties(notes_cfg: HostConfig, notes_db: FakeDb) -> None:
    for i in range(5):
        add_note(notes_db, title=f"t{i}", note_date="2026-02-02")
    seen: list[str] = []
    cursor = None
    while True:
        page = repo.list_notes(notes_cfg, USER, limit=2, before=cursor)
        seen += [i.title for i in page.items]
        cursor = page.next_cursor
        if not cursor:
            break
    assert sorted(seen) == ["t0", "t1", "t2", "t3", "t4"]


def test_list_rejects_a_malformed_cursor(notes_cfg: HostConfig) -> None:
    with pytest.raises(repo.InvalidCursor) as err:
        repo.list_notes(notes_cfg, USER, before="not-a-cursor")
    assert (err.value.status, err.value.body) == (422, {"error": "invalid_cursor"})


def test_list_clamps_the_limit(notes_cfg: HostConfig, notes_db: FakeDb) -> None:
    for i in range(3):
        add_note(notes_db, title=f"n{i}")
    assert len(repo.list_notes(notes_cfg, USER, limit=0).items) == 1
    assert len(repo.list_notes(notes_cfg, USER, limit=10_000).items) == 3


def test_include_deleted(notes_cfg: HostConfig, notes_db: FakeDb) -> None:
    add_note(notes_db, title="live")
    add_note(notes_db, title="gone", deleted_at="2026-10-01 10:00:00")
    assert titles(notes_cfg) == ["live"]
    assert sorted(titles(notes_cfg, include_deleted=True)) == ["gone", "live"]
    gone = next(
        i for i in repo.list_notes(notes_cfg, USER, include_deleted=True).items if i.title == "gone"
    )
    assert gone.deleted_at is not None


def test_sync_sources_aggregate_imported_workspaces(
    notes_cfg: HostConfig, notes_db: FakeDb
) -> None:
    def src(workspace: str, synced: str, **cols: Any) -> None:
        add_note(
            notes_db,
            origin="source",
            source_system="obsidian",
            source_workspace=workspace,
            last_synced_at=synced,
            **cols,
        )

    src("Dave2025", "2026-10-17 09:00:00")
    src("Dave2025", "2026-10-18 09:00:00")
    src("Dave2025", "2026-10-19 09:00:00", deleted_at="2026-10-19 10:00:00")
    src("Work", "2026-10-01 09:00:00")
    add_note(notes_db, title="mine")  # origin=app is never a sync source
    add_note(notes_db, OTHER, origin="source", source_system="obsidian", source_workspace="X")

    # Filters and paging do not change the aggregate.
    sources = repo.list_notes(notes_cfg, USER, kind="nothing", limit=1).sync_sources
    assert [(s.source_system, s.source_workspace, s.note_count) for s in sources] == [
        ("obsidian", "Dave2025", 2),
        ("obsidian", "Work", 1),
    ]
    assert sources[0].last_synced_at.startswith("2026-10-19")  # type: ignore[union-attr]


# --- patch ------------------------------------------------------------------------------------


def test_patch_edits_an_app_note_and_advances_its_version(
    notes_cfg: HostConfig, notes_db: FakeDb
) -> None:
    note_id = add_note(notes_db, title="Old", body_md="old", person="Roy")
    note = repo.patch_note(
        notes_cfg, USER, note_id, NotePatch(title="New", body_md="new", person=None)
    )
    assert (note.title, note.body_md, note.person, note.version) == ("New", "new", None, 2)
    # An omitted field is untouched; null on a NOT NULL column is ignored.
    note = repo.patch_note(notes_cfg, USER, note_id, NotePatch(place="Paris", title=None))
    assert (note.title, note.place, note.version) == ("New", "Paris", 3)


def test_patch_with_nothing_to_change_is_a_no_op(notes_cfg: HostConfig, notes_db: FakeDb) -> None:
    note_id = add_note(notes_db)
    assert repo.patch_note(notes_cfg, USER, note_id, NotePatch()).version == 1


def test_patch_of_an_import_allows_only_the_metadata_fields(
    notes_cfg: HostConfig, notes_db: FakeDb
) -> None:
    note_id = add_note(notes_db, origin="source", title="Imported", body_md="verbatim")
    for edit in ({"title": "X"}, {"body_md": "X"}, {"title": "X", "kind": "lecture"}):
        with pytest.raises(repo.ReadOnlyImport) as err:
            repo.patch_note(notes_cfg, USER, note_id, NotePatch(**edit))
        assert (err.value.status, err.value.body) == (409, {"error": "read_only_import"})
    note = repo.patch_note(
        notes_cfg,
        USER,
        note_id,
        NotePatch(kind="masterclass", person="Roy", note_date="2026-10-18", place="Paris"),
    )
    assert (note.title, note.body_md) == ("Imported", "verbatim")
    assert (note.kind, note.person, note.note_date, note.place) == (
        "masterclass",
        "Roy",
        "2026-10-18",
        "Paris",
    )
    assert note.version == 1  # imports have no autosave version to advance
    # The rejected request wrote nothing at all.
    assert repo.get_note(notes_cfg, USER, note_id).title == "Imported"


def test_patch_is_scoped_and_404s(notes_cfg: HostConfig, notes_db: FakeDb) -> None:
    theirs = add_note(notes_db, OTHER)
    with pytest.raises(repo.NoteNotFound):
        repo.patch_note(notes_cfg, USER, theirs, NotePatch(title="x"))


# --- autosave ---------------------------------------------------------------------------------


def test_autosave_saves_on_a_matching_version(notes_cfg: HostConfig, notes_db: FakeDb) -> None:
    note_id = add_note(notes_db, body_md="v1")
    result = repo.autosave_note(notes_cfg, USER, note_id, AutosaveBody(body_md="v2", version=1))
    assert result.conflict is None and result.note is not None
    assert (result.note.body_md, result.note.version) == ("v2", 2)
    assert result.model_dump(exclude_none=True).keys() == {"note"}


def test_autosave_conflict_returns_the_server_copy_and_writes_nothing(
    notes_cfg: HostConfig, notes_db: FakeDb
) -> None:
    note_id = add_note(notes_db, body_md="server", version=4)
    result = repo.autosave_note(notes_cfg, USER, note_id, AutosaveBody(body_md="stale", version=3))
    assert result.conflict is True and result.note is None
    assert result.server_version == 4
    assert result.server_data is not None and result.server_data.body_md == "server"
    assert repo.get_note(notes_cfg, USER, note_id).body_md == "server"
    # Replaying a save at the stale version after a good one conflicts too.
    repo.autosave_note(notes_cfg, USER, note_id, AutosaveBody(body_md="mine", version=4))
    again = repo.autosave_note(notes_cfg, USER, note_id, AutosaveBody(body_md="x", version=4))
    assert again.conflict is True and again.server_version == 5


def test_autosave_is_for_app_notes_only(notes_cfg: HostConfig, notes_db: FakeDb) -> None:
    note_id = add_note(notes_db, origin="source")
    with pytest.raises(repo.ReadOnlyImport):
        repo.autosave_note(notes_cfg, USER, note_id, AutosaveBody(body_md="x", version=1))
    with pytest.raises(repo.NoteNotFound):
        repo.autosave_note(notes_cfg, USER, 9999, AutosaveBody(body_md="x", version=1))


# --- delete -----------------------------------------------------------------------------------


def test_delete_cascades_links_and_attachment_rows_but_not_blobs(
    notes_cfg: HostConfig, notes_db: FakeDb
) -> None:
    note_id = add_note(notes_db)
    keep = add_note(notes_db, title="keep")
    blob_id, _ = add_blob(notes_db)
    attach(notes_db, note_id, blob_id, "![[a.webp]]")
    attach(notes_db, keep, blob_id, "![[a.webp]]")
    add_link(notes_db, note_id, "repertoire", 35, backlog_id=77)
    add_link(notes_db, keep, "repertoire", 35)

    assert repo.delete_note(notes_cfg, USER, note_id) is None

    def count(table: str, column: str, value: int) -> int:
        return notes_db.run(f"SELECT COUNT(*) AS n FROM {table} WHERE {column} = %s", [value])[0][
            "n"
        ]

    assert count("notes", "id", note_id) == 0
    assert count("note_links", "note_id", note_id) == 0
    assert count("note_attachments", "note_id", note_id) == 0
    assert count("blobs", "id", blob_id) == 1  # blobs are refcounted and collected later
    assert count("notes", "id", keep) == 1
    assert count("note_links", "note_id", keep) == 1
    assert count("note_attachments", "note_id", keep) == 1


def test_delete_removes_an_imported_note_too_and_404s(
    notes_cfg: HostConfig, notes_db: FakeDb
) -> None:
    imported = add_note(notes_db, origin="source", source_system="obsidian")
    theirs = add_note(notes_db, OTHER)
    repo.delete_note(notes_cfg, USER, imported)
    for note_id in (imported, theirs, 9999):
        with pytest.raises(repo.NoteNotFound):
            repo.delete_note(notes_cfg, USER, note_id)
    assert notes_db.run("SELECT id FROM notes WHERE id = %s", [theirs])
