"""Postgres BYTEA Storage adapter with chunked reads (D16). Owner: C2b (ga-mxal.26).

One row per (user_id, sha256) in a host-owned table (PT: `note_blobs`). The core never creates it:
the host applies `PostgresStorage.ddl(table)` in its own migration, which is why the table is not
part of `arp_notes.schema.ddl()`.

Reads are chunked: `open` slices the BYTEA with `substring(bytes from <offset> for <n>)`, one
statement per chunk, so no read ever holds more than one chunk (256 KiB by default). Writes
cannot be chunked over a single INSERT, so `put` buffers the blob once and is bounded by
`max_bytes` (the 25 MiB attachment cap, ADR D12).

SQL uses `%s` placeholders and goes through the host's `Db` port only: no connections of its own.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from typing import BinaryIO

from arp_notes.ports import Db

CHUNK_BYTES = 256 * 1024  # D16: serve in 256 KiB slices (the port allows up to 1 MiB)
MAX_CHUNK_BYTES = 1024 * 1024  # the Storage port promises chunks of at most 1 MiB
MAX_BLOB_BYTES = 25 * 1024 * 1024  # ADR D12, same as ports.Policy.max_attachment_bytes

_SHA256 = re.compile(r"[0-9a-f]{64}")
# A bare or schema-qualified identifier. The table name is spliced into SQL, so nothing else.
_TABLE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)?")

# The ADR A.1 PT-delta block, with the table name as the one variable part.
_DDL = """\
CREATE TABLE IF NOT EXISTS {table} (
    user_id TEXT NOT NULL,
    sha256 TEXT NOT NULL,                       -- matches blobs.sha256
    mime TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    bytes BYTEA NOT NULL,                       -- served by chunked reads only (D16)
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (user_id, sha256)
);
"""


def _check_table(table: str) -> str:
    if not _TABLE.fullmatch(table):
        raise ValueError(f"not a table name: {table!r}")
    return table


class PostgresStorage:
    def __init__(
        self,
        db: Db,
        table: str = "note_blobs",
        *,
        chunk_bytes: int = CHUNK_BYTES,
        max_bytes: int = MAX_BLOB_BYTES,
    ) -> None:
        if not 0 < chunk_bytes <= MAX_CHUNK_BYTES:
            raise ValueError(f"chunk_bytes must be in 1..{MAX_CHUNK_BYTES}, got {chunk_bytes}")
        if max_bytes < 0:
            raise ValueError(f"max_bytes must not be negative, got {max_bytes}")
        self._db = db
        self._table = _check_table(table)
        self._chunk_bytes = chunk_bytes
        self._max_bytes = max_bytes

    @staticmethod
    def ddl(table: str = "note_blobs") -> str:
        """The CREATE TABLE statement for `table`, idempotent (IF NOT EXISTS).

        For the default name this is the ADR A.1 PT-delta block, which PT migration 043 copies.
        """
        return _DDL.format(table=_check_table(table))

    def put(
        self, user_id: str, sha256: str, stream: BinaryIO, *, mime: str, size_bytes: int
    ) -> str:
        """Insert the bytes and return the locator, which for this backend is the sha256.

        Idempotent: when a row for (user_id, sha256) exists nothing is read or written. The core
        has already verified sha256 and size, so only the length is checked here.
        """
        _check_sha256(sha256)
        if size_bytes > self._max_bytes:
            raise ValueError(f"{size_bytes} bytes exceeds the {self._max_bytes} byte limit")
        if self._db.run(
            f"SELECT 1 FROM {self._table} WHERE user_id = %s AND sha256 = %s",
            [user_id, sha256],
        ):
            return sha256
        # Read one byte past the declared size so an overlong stream is caught without
        # buffering all of it.
        data = stream.read(size_bytes + 1)
        if len(data) != size_bytes:
            raise ValueError(f"expected {size_bytes} bytes for {sha256}, got {len(data)}")
        # ON CONFLICT covers the race between the check above and this insert.
        self._db.run(
            f"INSERT INTO {self._table} (user_id, sha256, mime, size_bytes, bytes) "
            "VALUES (%s, %s, %s, %s, %s) ON CONFLICT (user_id, sha256) DO NOTHING",
            [user_id, sha256, mime, size_bytes, data],
        )
        return sha256

    def open(self, user_id: str, sha256: str) -> Iterator[bytes]:
        """Yield the bytes in chunks of at most `chunk_bytes`. Raises LookupError when absent.

        The size lookup happens here, not on the first `next()`, so a missing blob fails the call.
        """
        _check_sha256(sha256)
        rows = self._db.run(
            f"SELECT octet_length(bytes) AS n FROM {self._table} "
            "WHERE user_id = %s AND sha256 = %s",
            [user_id, sha256],
        )
        if not rows:
            raise LookupError(f"no stored bytes for {sha256}")
        return self._chunks(user_id, sha256, int(rows[0]["n"]))

    def _chunks(self, user_id: str, sha256: str, total: int) -> Iterator[bytes]:
        sql = (
            f"SELECT substring(bytes from %s for %s) AS chunk FROM {self._table} "
            "WHERE user_id = %s AND sha256 = %s"
        )
        for start in range(0, total, self._chunk_bytes):
            # substring() is 1-based.
            rows = self._db.run(sql, [start + 1, self._chunk_bytes, user_id, sha256])
            if not rows:  # deleted between chunks
                raise LookupError(f"stored bytes for {sha256} vanished mid-read")
            yield bytes(rows[0]["chunk"])

    def delete(self, user_id: str, sha256: str) -> None:
        """Remove the row. Idempotent: absent is not an error.

        Deleting leaves TOAST bloat; hosts run VACUUM on the table after a blob GC sweep.
        """
        _check_sha256(sha256)
        self._db.run(
            f"DELETE FROM {self._table} WHERE user_id = %s AND sha256 = %s", [user_id, sha256]
        )


def _check_sha256(sha256: str) -> None:
    if not _SHA256.fullmatch(sha256):
        raise ValueError(f"not a lowercase sha256 hex digest: {sha256!r}")
