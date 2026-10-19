"""S3 Storage adapter (optional `s3` extra). Owner: C2b (ga-mxal.26)."""

from __future__ import annotations

from collections.abc import Iterator
from typing import BinaryIO


class S3Storage:
    def __init__(self, bucket: str, prefix: str = "") -> None:
        raise NotImplementedError("C2b: S3Storage")

    def put(self, sha256: str, stream: BinaryIO) -> str:
        raise NotImplementedError("C2b: S3Storage.put")

    def open(self, sha256: str) -> Iterator[bytes]:
        raise NotImplementedError("C2b: S3Storage.open")

    def delete(self, sha256: str) -> None:
        raise NotImplementedError("C2b: S3Storage.delete")
