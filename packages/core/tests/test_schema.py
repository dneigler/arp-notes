"""DDL 001 (ADR A.1 + K§1): idempotent, app-agnostic, and returned by schema.ddl()."""

from __future__ import annotations

import re
from importlib import resources

from arp_notes import schema
from arp_notes.testing.fakedb import FakeDb


def test_ddl_returns_the_checked_in_file() -> None:
    path = resources.files("arp_notes") / "sql" / "001_notes.sql"
    assert schema.ddl() == path.read_text(encoding="utf-8")


def test_every_statement_is_guarded() -> None:
    statements = [s.strip() for s in re.sub(r"--[^\n]*", "", schema.ddl()).split(";") if s.strip()]
    assert statements
    for stmt in statements:
        assert re.match(r"(CREATE (UNIQUE )?(TABLE|INDEX) IF NOT EXISTS)", stmt), stmt[:80]


def test_ddl_applies_twice_without_error(fakedb: FakeDb) -> None:
    fakedb.run(schema.ddl())
    fakedb.run(schema.ddl())
    notes_db_tables = fakedb.run(
        "SELECT count(*) AS n FROM information_schema.tables WHERE table_schema = 'public'"
    )
    assert notes_db_tables == [{"n": 6}]


def test_ddl_has_no_host_specific_pieces() -> None:
    text = schema.ddl().lower()
    assert "practice_backlog" not in text  # PT-only ALTER (A.1)
    assert "note_blobs" not in text  # PT-only Postgres blob table (D16)
    assert "references users" not in text  # no users table, no FK on user_id


def test_k1_additions_are_in_the_notes_table(notes_db: FakeDb) -> None:
    cols = {
        r["column_name"]: r
        for r in notes_db.run(
            "SELECT column_name, data_type, is_nullable, column_default "
            "FROM information_schema.columns WHERE table_name = 'notes'"
        )
    }
    assert cols["proposal"]["data_type"] == "jsonb"
    assert cols["proposed_at"]["data_type"].startswith("timestamp")
    assert cols["review_pending"]["is_nullable"] == "NO"
    assert cols["review_pending"]["column_default"] == "0"


def test_hygiene_dismissals_is_unique_per_user_and_key(notes_db: FakeDb) -> None:
    insert = "INSERT INTO hygiene_dismissals (user_id, issue_key) VALUES (%s, %s)"
    notes_db.run(insert, ["u1", "k"])
    notes_db.run(insert, ["u2", "k"])  # another user may dismiss the same key
    try:
        notes_db.run(insert, ["u1", "k"])
    except Exception as exc:  # psycopg.errors.UniqueViolation
        assert "unique" in str(exc).lower()
    else:
        raise AssertionError("duplicate (user_id, issue_key) was accepted")


def test_source_identity_is_unique_per_user_when_a_doc_id_is_set(notes_db: FakeDb) -> None:
    insert = (
        "INSERT INTO notes (user_id, title, source_system, source_workspace, source_doc_id) "
        "VALUES (%s, 't', 'obsidian', 'vault', %s)"
    )
    notes_db.run(insert, ["u1", "doc-1"])
    notes_db.run(insert, ["u2", "doc-1"])
    notes_db.run(insert, ["u1", None])  # no doc id: app-authored notes never collide
    notes_db.run(insert, ["u1", None])
    try:
        notes_db.run(insert, ["u1", "doc-1"])
    except Exception as exc:
        assert "unique" in str(exc).lower()
    else:
        raise AssertionError("duplicate source identity was accepted")


def test_note_delete_cascades_to_links_and_attachments(notes_db: FakeDb) -> None:
    note_id = notes_db.run("INSERT INTO notes (user_id, title) VALUES ('u', 't') RETURNING id")[0][
        "id"
    ]
    blob_id = notes_db.run(
        "INSERT INTO blobs (user_id, sha256, mime, size_bytes, storage_path) "
        "VALUES ('u', %s, 'image/png', 1, 'p') RETURNING id",
        ["a" * 64],
    )[0]["id"]
    notes_db.run(
        "INSERT INTO note_attachments (note_id, blob_id, filename, ref_in_markdown) "
        "VALUES (%s, %s, 'f', 'r')",
        [note_id, blob_id],
    )
    notes_db.run(
        "INSERT INTO note_links (note_id, user_id, entity_type, entity_id) "
        "VALUES (%s, 'u', 'x', 1)",
        [note_id],
    )
    notes_db.run("DELETE FROM notes WHERE id = %s", [note_id])
    assert notes_db.run("SELECT count(*) AS n FROM note_links") == [{"n": 0}]
    assert notes_db.run("SELECT count(*) AS n FROM note_attachments") == [{"n": 0}]
    assert notes_db.run("SELECT count(*) AS n FROM blobs") == [{"n": 1}]  # blobs outlive notes


def test_migration_002_adds_the_lane_to_a_database_that_has_only_001(fakedb: FakeDb) -> None:
    fakedb.run(schema.ddl())  # a host that applied 001 before 002 existed
    names = [name for name, _ in schema.migrations()]
    assert names == ["002_note_links_lane.sql"]
    for _name, text in schema.migrations():
        fakedb.run(text)
        fakedb.run(text)  # idempotent
    cols = {
        r["column_name"]: r
        for r in fakedb.run(
            "SELECT column_name, is_nullable FROM information_schema.columns"
            " WHERE table_name = 'note_links'"
        )
    }
    assert cols["lane"]["is_nullable"] == "YES"
