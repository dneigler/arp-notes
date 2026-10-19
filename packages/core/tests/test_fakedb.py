"""FakeDb behaves like a `ports.Db` over real Postgres (usable by every core bead)."""

from __future__ import annotations

import pytest
from arp_notes.ports import Db
from arp_notes.testing.fakedb import FakeDb, _format_placeholders


def test_fakedb_satisfies_the_db_port(fakedb: FakeDb) -> None:
    db: Db = fakedb
    assert isinstance(db, Db)


def test_run_returns_dict_rows_and_empty_list_for_statements(fakedb: FakeDb) -> None:
    assert fakedb.run("CREATE TABLE t (id SERIAL PRIMARY KEY, name TEXT, doc JSONB)") == []
    rows = fakedb.run(
        "INSERT INTO t (name, doc) VALUES (%s, %s) RETURNING id, name, doc",
        ["a", '{"k": [1, 2]}'],
    )
    assert rows == [{"id": 1, "name": "a", "doc": {"k": [1, 2]}}]
    assert fakedb.run("SELECT name FROM t WHERE id = ?", [1]) == [{"name": "a"}]


def test_both_placeholder_styles_work_in_one_statement_family(fakedb: FakeDb) -> None:
    assert fakedb.run("SELECT %s::int + ?::int AS n", [1, 2]) == [{"n": 3}]
    assert fakedb.run("SELECT 'a?b' AS s, ?::int AS n", [5]) == [{"n": 5, "s": "a?b"}]
    assert fakedb.run("SELECT 'a%b' AS s, ?::int AS n", [5]) == [{"n": 5, "s": "a%b"}]


@pytest.mark.parametrize(
    ("sql", "expected"),
    [
        ("a = ?", "a = %s"),
        ("a = %s", "a = %s"),
        ("'?' || ?", "'?' || %s"),
        ('"c?" = ?', '"c?" = %s'),
        ("'it''s ?' = ?", "'it''s ?' = %s"),
        ("x LIKE 'a%'", "x LIKE 'a%%'"),
        ("-- why? 50%\nselect ?", "-- why? 50%%\nselect %s"),
    ],
)
def test_placeholder_rewrite(sql: str, expected: str) -> None:
    assert _format_placeholders(sql) == expected


def test_transaction_commits_on_success(fakedb: FakeDb) -> None:
    fakedb.run("CREATE TABLE t (n INT)")
    with fakedb.transaction():
        fakedb.run("INSERT INTO t VALUES (1)")
    assert fakedb.run("SELECT n FROM t") == [{"n": 1}]


def test_transaction_rolls_back_on_error_and_nests_as_savepoints(fakedb: FakeDb) -> None:
    fakedb.run("CREATE TABLE t (n INT)")
    with pytest.raises(RuntimeError), fakedb.transaction():
        fakedb.run("INSERT INTO t VALUES (1)")
        raise RuntimeError("boom")
    assert fakedb.run("SELECT n FROM t") == []

    with fakedb.transaction():
        fakedb.run("INSERT INTO t VALUES (2)")
        with pytest.raises(RuntimeError), fakedb.transaction():
            fakedb.run("INSERT INTO t VALUES (3)")
            raise RuntimeError("inner")
    assert fakedb.run("SELECT n FROM t") == [{"n": 2}]


def test_each_test_gets_a_fresh_database(fakedb: FakeDb) -> None:
    assert fakedb.run("SELECT to_regclass('notes') AS t") == [{"t": None}]


def test_notes_db_has_the_core_schema(notes_db: FakeDb) -> None:
    tables = {
        r["table_name"]
        for r in notes_db.run(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"
        )
    }
    assert {
        "notes",
        "blobs",
        "note_attachments",
        "note_links",
        "upload_tickets",
        "hygiene_dismissals",
    } <= tables
