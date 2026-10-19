"""sync.upsert: identity, created/updated/unchanged, attachments, anchors (C1b, ga-mxal.8)."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import pytest
from arp_notes import repo, review, sync
from arp_notes.anchors import slug
from arp_notes.config import HostConfig
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

TWO_HEADINGS = "# Intro\n\n## Etude 3\n\ntext\n\n## Etude 4\n\nmore\n"


def note_row(db: FakeDb, note_id: int) -> dict[str, Any]:
    return db.run("SELECT * FROM notes WHERE id = %s", [note_id])[0]


def link_statuses(db: FakeDb, note_id: int) -> dict[str, str]:
    rows = db.run("SELECT anchor, status FROM note_links WHERE note_id = %s", [note_id])
    return {str(r["anchor"]): r["status"] for r in rows}


@pytest.fixture
def after_upsert_calls(monkeypatch: pytest.MonkeyPatch) -> list[tuple[int, str]]:
    calls: list[tuple[int, str]] = []
    monkeypatch.setattr(
        review,
        "after_upsert",
        lambda cfg, user_id, note_id, outcome: calls.append((note_id, outcome)),
    )
    return calls


# --- created / unchanged / updated ------------------------------------------------------------


def test_first_upsert_creates_a_source_note(
    notes_cfg: HostConfig, notes_db: FakeDb, fake_hooks: FakeHooks, after_upsert_calls: list[Any]
) -> None:
    body = upsert_body(
        "d1",
        "---\ntitle: x\n---\n# Intro\n",
        frontmatter={"title": "x"},
        kind="masterclass",
        person="Roy",
        note_date="2026-10-18",
        place="Paris",
        source_url="obsidian://open?vault=Vault&file=d1",
        source_modified_at="2026-10-18T10:00:00Z",
    )
    result = sync.upsert(notes_cfg, USER, body)
    assert result.model_dump(exclude={"hygiene"}) == {
        "note_id": result.note_id,
        "outcome": "created",
        "missing_attachments": [],
        "links_orphaned": 0,
    }
    row = note_row(notes_db, result.note_id)
    assert (row["origin"], row["user_id"], row["created_via"], row["version"]) == (
        "source",
        USER,
        "cli",
        1,
    )
    assert (row["title"], row["body_md"], row["content_hash"]) == (
        "Note d1",
        body.body_md,
        body.content_hash,
    )
    assert row["frontmatter"] == {"title": "x"}
    assert (row["kind"], row["person"], row["note_date"], row["place"]) == (
        "masterclass",
        "Roy",
        "2026-10-18",
        "Paris",
    )
    assert (row["source_system"], row["source_workspace"], row["source_doc_id"]) == (
        "obsidian",
        "Vault",
        "d1",
    )
    assert row["source_url"].startswith("obsidian://") and row["last_synced_at"] is not None
    assert row["deleted_at"] is None

    [(user, event, entity, summary)] = fake_hooks.events
    assert (user, event) == (USER, "note_synced")
    assert entity["origin"] == "source" and entity["source_workspace"] == "Vault"
    assert entity["note_id"] == result.note_id and entity["entity_type"] == "note"
    assert "obsidian" in summary and "Note d1" in summary
    assert after_upsert_calls == [(result.note_id, "created")]


def test_defaults_when_the_source_gives_no_metadata(
    notes_cfg: HostConfig, notes_db: FakeDb
) -> None:
    result = sync.upsert(notes_cfg, USER, upsert_body())
    row = note_row(notes_db, result.note_id)
    assert (row["kind"], row["frontmatter"], row["person"]) == ("note", {}, None)
    assert note_row(notes_db, result.note_id)["created_via"] == "cli"
    mcp = sync.upsert(notes_cfg, USER, upsert_body("d2"), created_via="mcp")
    assert note_row(notes_db, mcp.note_id)["created_via"] == "mcp"


def test_the_same_upsert_twice_is_unchanged(
    notes_cfg: HostConfig, fake_hooks: FakeHooks, after_upsert_calls: list[Any]
) -> None:
    first = sync.upsert(notes_cfg, USER, upsert_body())
    again = sync.upsert(notes_cfg, USER, upsert_body())
    assert (again.outcome, again.note_id) == ("unchanged", first.note_id)
    # Nothing changed, so no activity and no re-proposal (K§3).
    assert fake_hooks.names() == ["note_synced"]
    assert after_upsert_calls == [(first.note_id, "created")]


def test_a_changed_hash_updates_in_place(
    notes_cfg: HostConfig, notes_db: FakeDb, fake_hooks: FakeHooks, after_upsert_calls: list[Any]
) -> None:
    first = sync.upsert(notes_cfg, USER, upsert_body(kind="masterclass", person="Roy"))
    fake_hooks.events.clear()
    new = upsert_body(
        "d1",
        "# Rewritten\n",
        title="New title",
        frontmatter={"k": 1},
        source_url="obsidian://new",
    )
    result = sync.upsert(notes_cfg, USER, new)
    assert (result.outcome, result.note_id) == ("updated", first.note_id)
    row = note_row(notes_db, first.note_id)
    assert (row["title"], row["body_md"], row["content_hash"]) == (
        "New title",
        "# Rewritten\n",
        new.content_hash,
    )
    assert (row["frontmatter"], row["source_url"]) == ({"k": 1}, "obsidian://new")
    # The request supplied no kind/person, so what the app holds stays.
    assert (row["kind"], row["person"]) == ("masterclass", "Roy")
    assert fake_hooks.names() == ["note_synced"]
    assert after_upsert_calls[-1] == (first.note_id, "updated")
    # Supplying them replaces.
    sync.upsert(notes_cfg, USER, upsert_body("d1", "# Third\n", kind="lecture", person="Ann"))
    assert (
        note_row(notes_db, first.note_id)["kind"],
        note_row(notes_db, first.note_id)["person"],
    ) == (
        "lecture",
        "Ann",
    )


def test_a_rename_keeps_the_id_and_follows_the_new_path_and_url(
    notes_cfg: HostConfig, notes_db: FakeDb
) -> None:
    first = sync.upsert(
        notes_cfg, USER, upsert_body(path="old/d1.md", source_url="obsidian://old", kind="lecture")
    )
    notes_db.run("UPDATE notes SET last_synced_at = '2020-01-01', title = 'Edited in app'")
    renamed = sync.upsert(
        notes_cfg, USER, upsert_body(path="new/d1.md", source_url="obsidian://new")
    )
    assert (renamed.outcome, renamed.note_id) == ("unchanged", first.note_id)
    row = note_row(notes_db, first.note_id)
    assert (row["source_path"], row["source_url"]) == ("new/d1.md", "obsidian://new")
    assert row["last_synced_at"].year > 2020
    assert row["title"] == "Edited in app"  # an unchanged body never rewrites the metadata
    assert notes_db.run("SELECT COUNT(*) AS n FROM notes")[0]["n"] == 1


def test_identity_is_per_user_system_workspace_and_doc(
    notes_cfg: HostConfig, notes_db: FakeDb
) -> None:
    ids = {
        sync.upsert(notes_cfg, USER, upsert_body()).note_id,
        sync.upsert(notes_cfg, OTHER, upsert_body()).note_id,
        sync.upsert(notes_cfg, USER, upsert_body(source_workspace="Other")).note_id,
        sync.upsert(notes_cfg, USER, upsert_body(source_system="notion")).note_id,
        sync.upsert(notes_cfg, USER, upsert_body("d2")).note_id,
    }
    assert len(ids) == 5


def test_losing_the_insert_race_falls_back_to_the_winners_row(
    notes_cfg: HostConfig, notes_db: FakeDb
) -> None:
    """Another request inserts the same triple between our SELECT and our INSERT."""
    winner = {"id": None}

    class Racing:
        def __init__(self, inner: FakeDb) -> None:
            self.inner = inner
            self.raced = False

        def run(self, sql: str, params: Sequence[Any] = ()) -> list[dict[str, Any]]:
            rows = self.inner.run(sql, params)
            if sql.startswith("SELECT id, content_hash") and not self.raced:
                self.raced = True
                assert rows == []
                winner["id"] = self.inner.run(
                    "INSERT INTO notes (user_id, title, origin, source_system, source_workspace,"
                    " source_doc_id, content_hash) VALUES (%s, 'won', 'source', 'obsidian',"
                    " 'Vault', 'd1', %s) RETURNING id",
                    [USER, sha("other")],
                )[0]["id"]
            return rows

        def transaction(self) -> Any:
            return self.inner.transaction()

    cfg = HostConfig(**{**notes_cfg.__dict__, "db": Racing(notes_db)})
    result = sync.upsert(cfg, USER, upsert_body())
    assert (result.note_id, result.outcome) == (winner["id"], "updated")
    assert notes_db.run("SELECT COUNT(*) AS n FROM notes")[0]["n"] == 1


def test_review_failures_are_swallowed(
    notes_cfg: HostConfig, notes_db: FakeDb, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(*_args: object) -> None:
        raise RuntimeError("proposal pipeline down")

    monkeypatch.setattr(review, "after_upsert", boom)
    assert sync.upsert(notes_cfg, USER, upsert_body()).outcome == "created"
    assert notes_db.run("SELECT COUNT(*) AS n FROM notes")[0]["n"] == 1


def test_the_stub_after_upsert_is_called_by_default(notes_cfg: HostConfig) -> None:
    assert sync.upsert(notes_cfg, USER, upsert_body()).outcome == "created"  # no-op until R1


def test_a_failing_activity_hook_is_swallowed(
    notes_cfg: HostConfig, fake_hooks: FakeHooks, after_upsert_calls: list[Any]
) -> None:
    def boom(*_args: object) -> None:
        raise RuntimeError("down")

    fake_hooks.on_event = boom
    result = sync.upsert(notes_cfg, USER, upsert_body())
    assert after_upsert_calls == [(result.note_id, "created")]  # still ran


# --- attachments ------------------------------------------------------------------------------


def attachment_rows(db: FakeDb, note_id: int) -> list[dict[str, Any]]:
    return db.run(
        "SELECT a.id, a.ref_in_markdown, a.filename, a.sort_order, b.sha256 FROM"
        " note_attachments a JOIN blobs b ON b.id = a.blob_id WHERE a.note_id = %s ORDER BY"
        " a.sort_order",
        [note_id],
    )


def test_unknown_blobs_are_reported_and_attach_on_the_next_upsert(
    notes_cfg: HostConfig, notes_db: FakeDb
) -> None:
    _, have = add_blob(notes_db, text="have")
    want = sha("not-uploaded-yet")
    refs = [attachment_ref(have, "![[a.webp]]"), attachment_ref(want, "![[b.webp]]")]
    body = upsert_body(body_md="![[a.webp]] ![[b.webp]]", attachments=refs)

    first = sync.upsert(notes_cfg, USER, body)
    assert first.missing_attachments == [want]
    assert [r["ref_in_markdown"] for r in attachment_rows(notes_db, first.note_id)] == [
        "![[a.webp]]"
    ]

    add_blob(notes_db, text="not-uploaded-yet")
    second = sync.upsert(notes_cfg, USER, body)  # same bytes, so the body is "unchanged"
    assert (second.outcome, second.missing_attachments) == ("unchanged", [])
    assert [r["ref_in_markdown"] for r in attachment_rows(notes_db, first.note_id)] == [
        "![[a.webp]]",
        "![[b.webp]]",
    ]


def test_another_users_blob_does_not_count(notes_cfg: HostConfig, notes_db: FakeDb) -> None:
    _, digest = add_blob(notes_db, OTHER, text="theirs")
    result = sync.upsert(
        notes_cfg, USER, upsert_body(attachments=[attachment_ref(digest, "![[a.webp]]")])
    )
    assert result.missing_attachments == [digest]
    assert attachment_rows(notes_db, result.note_id) == []


def test_two_identical_screenshots_share_one_blob(notes_cfg: HostConfig, notes_db: FakeDb) -> None:
    _, digest = add_blob(notes_db, text="same")
    refs = [attachment_ref(digest, "![[one.webp]]"), attachment_ref(digest, "![[two.webp]]")]
    result = sync.upsert(notes_cfg, USER, upsert_body(attachments=refs))
    assert result.missing_attachments == []
    assert [r["sha256"] for r in attachment_rows(notes_db, result.note_id)] == [digest, digest]


def test_a_repeated_ref_in_one_request_keeps_the_first(
    notes_cfg: HostConfig, notes_db: FakeDb
) -> None:
    _, a = add_blob(notes_db, text="a")
    _, b = add_blob(notes_db, text="b")
    refs = [attachment_ref(a, "![[x.webp]]"), attachment_ref(b, "![[x.webp]]")]
    result = sync.upsert(notes_cfg, USER, upsert_body(attachments=refs))
    assert [r["sha256"] for r in attachment_rows(notes_db, result.note_id)] == [a]
    assert result.missing_attachments == []


def test_attachments_are_rebuilt_by_ref_on_update(notes_cfg: HostConfig, notes_db: FakeDb) -> None:
    _, a = add_blob(notes_db, text="a")
    _, b = add_blob(notes_db, text="b")
    _, c = add_blob(notes_db, text="c")
    first = sync.upsert(
        notes_cfg,
        USER,
        upsert_body(
            body_md="v1",
            attachments=[attachment_ref(a, "![[a.webp]]"), attachment_ref(b, "![[b.webp]]")],
        ),
    )
    ids = {r["ref_in_markdown"]: r["id"] for r in attachment_rows(notes_db, first.note_id)}

    sync.upsert(
        notes_cfg,
        USER,
        upsert_body(
            body_md="v2",
            attachments=[
                attachment_ref(c, "![[c.webp]]"),  # new, and now first
                attachment_ref(a, "![[a.webp]]"),  # kept
                # b is gone from the body
            ],
        ),
    )
    rows = attachment_rows(notes_db, first.note_id)
    assert [(r["ref_in_markdown"], r["sha256"]) for r in rows] == [
        ("![[c.webp]]", c),
        ("![[a.webp]]", a),
    ]
    assert {r["ref_in_markdown"]: r["id"] for r in rows}["![[a.webp]]"] == ids["![[a.webp]]"]

    # A ref now pointing at different bytes is repointed, not duplicated.
    sync.upsert(
        notes_cfg, USER, upsert_body(body_md="v3", attachments=[attachment_ref(b, "![[a.webp]]")])
    )
    assert [
        (r["ref_in_markdown"], r["sha256"]) for r in attachment_rows(notes_db, first.note_id)
    ] == [("![[a.webp]]", b)]

    # An attachment whose new bytes are not uploaded yet drops the stale row and is reported.
    gone = sha("never")
    result = sync.upsert(
        notes_cfg,
        USER,
        upsert_body(body_md="v4", attachments=[attachment_ref(gone, "![[a.webp]]")]),
    )
    assert result.missing_attachments == [gone]
    assert attachment_rows(notes_db, first.note_id) == []


# --- anchors: orphaning and restoring ---------------------------------------------------------


def seed_links(db: FakeDb, note_id: int) -> None:
    add_link(db, note_id, "repertoire", 35, anchor=slug("Etude 3"))
    add_link(db, note_id, "composer", 1, anchor=slug("Etude 3"))
    add_link(db, note_id, "repertoire", 36, anchor=slug("Etude 4"))
    add_link(db, note_id, "technique", 7, anchor=None)  # whole note
    add_link(db, note_id, "movement", 3, anchor="gone", status="rejected")


def test_editing_one_heading_orphans_only_that_anchors_links(
    notes_cfg: HostConfig, notes_db: FakeDb
) -> None:
    note_id = sync.upsert(notes_cfg, USER, upsert_body(body_md=TWO_HEADINGS)).note_id
    seed_links(notes_db, note_id)

    edited = TWO_HEADINGS.replace("## Etude 3", "## Étude trois")
    result = sync.upsert(notes_cfg, USER, upsert_body(body_md=edited))
    assert (result.outcome, result.links_orphaned) == ("updated", 2)
    rows = notes_db.run("SELECT entity_id, anchor, status FROM note_links ORDER BY id")
    assert [(r["entity_id"], r["status"]) for r in rows] == [
        (35, "orphaned"),
        (1, "orphaned"),
        (36, "confirmed"),
        (7, "confirmed"),
        (3, "rejected"),  # a rejection is a suppression marker, not a passage
    ]
    # Orphaned links are kept, not deleted, and the note still lists them.
    assert len(repo.get_note(notes_cfg, USER, note_id).links) == 4


def test_a_link_comes_back_when_its_heading_does(notes_cfg: HostConfig, notes_db: FakeDb) -> None:
    note_id = sync.upsert(notes_cfg, USER, upsert_body(body_md=TWO_HEADINGS)).note_id
    seed_links(notes_db, note_id)
    sync.upsert(notes_cfg, USER, upsert_body(body_md="# Intro\n"))
    assert set(link_statuses(notes_db, note_id).values()) == {"orphaned", "confirmed", "rejected"}

    result = sync.upsert(notes_cfg, USER, upsert_body(body_md=TWO_HEADINGS))
    assert result.links_orphaned == 0
    assert link_statuses(notes_db, note_id) == {
        slug("Etude 3"): "confirmed",
        slug("Etude 4"): "confirmed",
        "None": "confirmed",
        "gone": "rejected",
    }


def test_unchanged_never_touches_links(notes_cfg: HostConfig, notes_db: FakeDb) -> None:
    note_id = sync.upsert(notes_cfg, USER, upsert_body(body_md=TWO_HEADINGS)).note_id
    add_link(notes_db, note_id, "repertoire", 35, anchor="not-in-the-body")
    result = sync.upsert(notes_cfg, USER, upsert_body(body_md=TWO_HEADINGS))
    assert (result.outcome, result.links_orphaned) == ("unchanged", 0)
    assert link_statuses(notes_db, note_id) == {"not-in-the-body": "confirmed"}


def test_block_id_anchors_follow_the_body(notes_cfg: HostConfig, notes_db: FakeDb) -> None:
    note_id = sync.upsert(notes_cfg, USER, upsert_body(body_md="Play this slowly ^slow\n")).note_id
    add_link(notes_db, note_id, "repertoire", 35, anchor="^slow")
    assert (
        sync.upsert(notes_cfg, USER, upsert_body(body_md="Still ^slow here\n")).links_orphaned == 1
    )
    assert sync.upsert(notes_cfg, USER, upsert_body(body_md="Now ^slow\n")).links_orphaned == 0
    assert link_statuses(notes_db, note_id) == {"^slow": "confirmed"}


# --- body_anchors -----------------------------------------------------------------------------


def test_body_anchors_reads_headings_and_block_ids() -> None:
    body = (
        "---\ntitle: T\n# yaml comment, not a heading\n---\n"
        "# Top\n\n"
        "## Étude 3 — *Tristesse*   \n"
        "### Closed ###\n"
        "####### seven hashes is not a heading\n"
        "#nospace is a tag\n"
        "A paragraph ^para-1\n"
        "> ## Quoted\n"
        "Setext one\n==========\n"
        "Setext two\n----------\n"
        "- list item\n---\n"
        "```\n# in a fence\n^fenced\n```\n"
        "~~~python\n# in a tilde fence\n~~~\n"
        "## After the fences\n"
    )
    assert sync.body_anchors(body) == {
        "top",
        "étude-3--tristesse",
        "closed",
        "^para-1",
        "quoted",
        "setext-one",
        "setext-two",
        "after-the-fences",
    }


def test_body_anchors_edge_cases() -> None:
    assert sync.body_anchors("") == set()
    assert sync.body_anchors("no headings here") == set()
    assert sync.body_anchors("# One\r\n## Two\r\n") == {"one", "two"}  # CRLF files
    assert sync.body_anchors("---\nunterminated frontmatter\n# Head\n") == {"head"}
    assert sync.body_anchors("﻿---\na: 1\n---\n# H\n") == {"h"}
    assert sync.body_anchors("# \n#\n") == set()
    # A fence of one kind is not closed by the other.
    assert sync.body_anchors("```\n~~~\n# still fenced\n```\n# out\n") == {"out"}
