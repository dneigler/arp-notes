"""storage.postgres: PostgresStorage DDL, idempotent put, 256 KiB chunked reads, per-user bytes
(C2b, ga-mxal.26). Runs against a real Postgres through FakeDb."""

from __future__ import annotations

import hashlib
import io
import os
from collections.abc import Sequence
from typing import Any

import pytest
from arp_notes.ports import Db, Storage
from arp_notes.storage.postgres import CHUNK_BYTES, PostgresStorage
from arp_notes.testing.fakedb import FakeDb

# The ADR A.1 PT-delta block, verbatim (migration 043 copies it).
ADR_A1_NOTE_BLOBS = """\
CREATE TABLE IF NOT EXISTS note_blobs (
    user_id TEXT NOT NULL,
    sha256 TEXT NOT NULL,                       -- matches blobs.sha256
    mime TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    bytes BYTEA NOT NULL,                       -- served by chunked reads only (D16)
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (user_id, sha256)
);
"""


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class CountingDb:
    """A Db that records every statement, to count the chunk reads."""

    def __init__(self, inner: Db) -> None:
        self._inner = inner
        self.statements: list[str] = []

    def run(self, sql: str, params: Sequence[Any] = ()) -> list[dict[str, Any]]:
        self.statements.append(sql)
        return self._inner.run(sql, params)

    def transaction(self) -> Any:
        return self._inner.transaction()

    def slices(self) -> list[str]:
        return [s for s in self.statements if "substring(" in s]


@pytest.fixture
def db(fakedb: FakeDb) -> FakeDb:
    fakedb.run(PostgresStorage.ddl())
    return fakedb


@pytest.fixture
def storage(db: FakeDb) -> PostgresStorage:
    return PostgresStorage(db)


def put(storage: PostgresStorage, user_id: str, data: bytes, mime: str = "image/png") -> str:
    return storage.put(user_id, digest(data), io.BytesIO(data), mime=mime, size_bytes=len(data))


def read(storage: PostgresStorage, user_id: str, data: bytes) -> bytes:
    return b"".join(storage.open(user_id, digest(data)))


def test_postgres_storage_is_a_storage(storage: PostgresStorage) -> None:
    assert isinstance(storage, Storage)


def test_ddl_is_the_adr_a1_block() -> None:
    assert PostgresStorage.ddl("note_blobs") == ADR_A1_NOTE_BLOBS
    assert PostgresStorage.ddl() == ADR_A1_NOTE_BLOBS


def test_ddl_takes_another_table_name_and_refuses_anything_that_is_not_one() -> None:
    assert PostgresStorage.ddl("app.blobs").startswith("CREATE TABLE IF NOT EXISTS app.blobs (")
    for bad in ("", "x; DROP TABLE notes", "a b", "1abc", "a.b.c", 'quo"te'):
        with pytest.raises(ValueError):
            PostgresStorage.ddl(bad)
        with pytest.raises(ValueError):
            PostgresStorage(None, bad)  # type: ignore[arg-type]


def test_ddl_is_idempotent_and_creates_the_pk(db: FakeDb) -> None:
    db.run(PostgresStorage.ddl())  # the fixture already ran it once
    columns = db.run(
        "SELECT column_name, is_nullable FROM information_schema.columns "
        "WHERE table_name = 'note_blobs' ORDER BY ordinal_position"
    )
    assert [c["column_name"] for c in columns] == [
        "user_id",
        "sha256",
        "mime",
        "size_bytes",
        "bytes",
        "created_at",
    ]
    assert [c["column_name"] for c in columns if c["is_nullable"] == "NO"] == [
        "user_id",
        "sha256",
        "mime",
        "size_bytes",
        "bytes",
    ]
    pk = db.run(
        "SELECT a.attname FROM pg_index i JOIN pg_attribute a "
        "ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey) "
        "WHERE i.indrelid = 'note_blobs'::regclass AND i.indisprimary ORDER BY a.attnum"
    )
    assert [r["attname"] for r in pk] == ["user_id", "sha256"]


def test_put_stores_the_row_and_returns_the_sha_as_locator(
    storage: PostgresStorage, db: FakeDb
) -> None:
    data = b"a screenshot"
    assert put(storage, "u1", data, mime="image/webp") == digest(data)
    (row,) = db.run("SELECT * FROM note_blobs")
    assert (row["user_id"], row["sha256"], row["mime"], row["size_bytes"]) == (
        "u1",
        digest(data),
        "image/webp",
        len(data),
    )
    assert bytes(row["bytes"]) == data


def test_put_is_idempotent_and_does_not_read_the_stream_the_second_time(
    storage: PostgresStorage, db: FakeDb
) -> None:
    data = b"same bytes"
    put(storage, "u1", data)
    stream = io.BytesIO(data)
    again = storage.put("u1", digest(data), stream, mime="image/png", size_bytes=len(data))
    assert again == digest(data)
    assert stream.tell() == 0
    assert db.run("SELECT count(*) AS n FROM note_blobs")[0]["n"] == 1


def test_put_survives_losing_the_race_to_a_concurrent_insert(db: FakeDb) -> None:
    """The row appears between the existence check and the INSERT: ON CONFLICT swallows it."""
    data = b"raced"

    class Racing(CountingDb):
        def run(self, sql: str, params: Sequence[Any] = ()) -> list[dict[str, Any]]:
            rows = super().run(sql, params)
            if sql.startswith("SELECT 1"):
                db.run(
                    "INSERT INTO note_blobs (user_id, sha256, mime, size_bytes, bytes) "
                    "VALUES (%s, %s, %s, %s, %s)",
                    ["u1", digest(data), "image/png", len(data), data],
                )
            return rows

    storage = PostgresStorage(Racing(db))
    assert put(storage, "u1", data) == digest(data)
    assert db.run("SELECT count(*) AS n FROM note_blobs")[0]["n"] == 1


def test_put_checks_the_length_it_was_promised(storage: PostgresStorage, db: FakeDb) -> None:
    data = b"twelve bytes"
    for size in (len(data) - 1, len(data) + 1):
        with pytest.raises(ValueError, match="expected"):
            storage.put("u1", digest(data), io.BytesIO(data), mime="image/png", size_bytes=size)
    assert db.run("SELECT count(*) AS n FROM note_blobs")[0]["n"] == 0


def test_put_is_bounded_by_the_size_cap_and_never_reads_past_it(db: FakeDb) -> None:
    storage = PostgresStorage(db, max_bytes=100)
    data = b"x" * 101
    stream = io.BytesIO(data)
    with pytest.raises(ValueError, match="limit"):
        storage.put("u1", digest(data), stream, mime="image/png", size_bytes=len(data))
    assert stream.tell() == 0
    put(storage, "u1", b"y" * 100)  # exactly the cap is fine


def test_default_cap_is_the_25_mb_attachment_policy() -> None:
    from arp_notes.ports import Policy
    from arp_notes.storage.postgres import MAX_BLOB_BYTES

    assert MAX_BLOB_BYTES == Policy().max_attachment_bytes == 25 * 1024 * 1024


def test_five_mb_round_trip_in_256_kib_chunks(db: FakeDb) -> None:
    counting = CountingDb(db)
    storage = PostgresStorage(counting)
    data = os.urandom(5 * 1024 * 1024)
    put(storage, "u1", data)

    counting.statements.clear()
    chunks = list(storage.open("u1", digest(data)))

    assert CHUNK_BYTES == 256 * 1024
    assert b"".join(chunks) == data
    assert len(chunks) == 20  # 5 MiB / 256 KiB
    assert {len(chunk) for chunk in chunks} == {256 * 1024}
    assert len(counting.slices()) == 20  # one bounded statement per chunk, never one big read


def test_open_streams_lazily_one_chunk_per_statement(db: FakeDb) -> None:
    counting = CountingDb(db)
    storage = PostgresStorage(counting)
    data = os.urandom(3 * CHUNK_BYTES)
    put(storage, "u1", data)

    counting.statements.clear()
    stream = storage.open("u1", digest(data))
    assert counting.slices() == []  # nothing fetched until iterated
    next(stream)
    assert len(counting.slices()) == 1
    next(stream)
    assert len(counting.slices()) == 2


def test_last_chunk_is_the_remainder_and_the_port_bound_holds(storage: PostgresStorage) -> None:
    data = os.urandom(2 * CHUNK_BYTES + 17)
    put(storage, "u1", data)
    chunks = list(storage.open("u1", digest(data)))
    assert [len(c) for c in chunks] == [CHUNK_BYTES, CHUNK_BYTES, 17]
    assert b"".join(chunks) == data
    assert all(isinstance(c, bytes) and len(c) <= 1024 * 1024 for c in chunks)


def test_chunk_size_is_configurable_up_to_the_port_bound(db: FakeDb) -> None:
    storage = PostgresStorage(db, chunk_bytes=1000)
    data = os.urandom(2500)
    put(storage, "u1", data)
    assert [len(c) for c in storage.open("u1", digest(data))] == [1000, 1000, 500]
    for bad in (0, -1, 1024 * 1024 + 1):
        with pytest.raises(ValueError):
            PostgresStorage(db, chunk_bytes=bad)


def test_empty_blob_round_trips(storage: PostgresStorage) -> None:
    put(storage, "u1", b"")
    assert list(storage.open("u1", digest(b""))) == []


def test_absent_blob_raises_lookup_error_when_open_is_called(storage: PostgresStorage) -> None:
    with pytest.raises(LookupError):
        storage.open("u1", digest(b"never stored"))  # not on first next()


def test_blob_deleted_mid_read_raises_lookup_error(storage: PostgresStorage, db: FakeDb) -> None:
    data = os.urandom(2 * CHUNK_BYTES)
    put(storage, "u1", data)
    stream = storage.open("u1", digest(data))
    next(stream)
    storage.delete("u1", digest(data))
    with pytest.raises(LookupError):
        next(stream)


def test_delete_removes_the_bytes_and_is_idempotent(storage: PostgresStorage) -> None:
    data = b"to delete"
    put(storage, "u1", data)
    storage.delete("u1", digest(data))
    with pytest.raises(LookupError):
        storage.open("u1", digest(data))
    storage.delete("u1", digest(data))  # absent is not an error
    storage.delete("u1", digest(b"never stored"))


def test_two_users_with_the_same_sha256_get_separate_rows(
    storage: PostgresStorage, db: FakeDb
) -> None:
    data = b"shared bytes"
    assert put(storage, "u1", data, mime="image/png") == put(storage, "u2", data, mime="image/jpeg")
    assert db.run("SELECT count(*) AS n FROM note_blobs")[0]["n"] == 2
    assert read(storage, "u1", data) == read(storage, "u2", data) == data

    storage.delete("u1", digest(data))
    with pytest.raises(LookupError):
        storage.open("u1", digest(data))
    assert read(storage, "u2", data) == data  # deleting one copy leaves the other


def test_one_user_cannot_read_another_users_bytes(storage: PostgresStorage) -> None:
    put(storage, "u1", b"private")
    with pytest.raises(LookupError):
        storage.open("u2", digest(b"private"))


def test_another_table_name_is_used_for_every_statement(fakedb: FakeDb) -> None:
    fakedb.run(PostgresStorage.ddl("app_blobs"))
    storage = PostgresStorage(fakedb, table="app_blobs")
    data = b"elsewhere"
    put(storage, "u1", data)
    assert read(storage, "u1", data) == data
    assert fakedb.run("SELECT count(*) AS n FROM app_blobs")[0]["n"] == 1
    storage.delete("u1", digest(data))
    assert fakedb.run("SELECT count(*) AS n FROM app_blobs")[0]["n"] == 0


@pytest.mark.parametrize("bad", ["", "ABC", "../etc/passwd", "g" * 64, digest(b"x").upper()])
def test_a_malformed_sha256_is_refused_before_any_sql(bad: str) -> None:
    class NoDb:
        def run(self, sql: str, params: Sequence[Any] = ()) -> list[dict[str, Any]]:
            raise AssertionError("no SQL for a bad digest")

        def transaction(self) -> Any:
            raise AssertionError

    storage = PostgresStorage(NoDb())
    with pytest.raises(ValueError):
        storage.put("u1", bad, io.BytesIO(b""), mime="image/png", size_bytes=0)
    with pytest.raises(ValueError):
        storage.open("u1", bad)
    with pytest.raises(ValueError):
        storage.delete("u1", bad)
