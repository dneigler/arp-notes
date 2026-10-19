"""Disk Storage adapter. Owner: C2 (ga-mxal.9)."""

from __future__ import annotations

from collections.abc import Iterator
from typing import BinaryIO


class DiskStorage:
    def __init__(self, root: str) -> None:
        raise NotImplementedError("C2: DiskStorage")

    def put(self, sha256: str, stream: BinaryIO) -> str:
        raise NotImplementedError("C2: DiskStorage.put")

    def open(self, sha256: str) -> Iterator[bytes]:
        raise NotImplementedError("C2: DiskStorage.open")

    def delete(self, sha256: str) -> None:
        raise NotImplementedError("C2: DiskStorage.delete")
