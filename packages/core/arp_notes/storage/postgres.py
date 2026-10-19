"""Postgres BYTEA Storage adapter with chunked reads (D16). Owner: C2b (ga-mxal.26)."""

from __future__ import annotations

from collections.abc import Iterator
from typing import BinaryIO

from arp_notes.ports import Db


class PostgresStorage:
    def __init__(self, db: Db, table: str = "note_blobs") -> None:
        raise NotImplementedError("C2b: PostgresStorage")

    def put(self, sha256: str, stream: BinaryIO) -> str:
        raise NotImplementedError("C2b: PostgresStorage.put")

    def open(self, sha256: str) -> Iterator[bytes]:
        raise NotImplementedError("C2b: PostgresStorage.open")

    def delete(self, sha256: str) -> None:
        raise NotImplementedError("C2b: PostgresStorage.delete")
