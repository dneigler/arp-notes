"""Disk Storage adapter. Owner: C2 (ga-mxal.9).

Layout (K§12.1): `<root>/<h>/<sha256[:2]>/<sha256>` with `h = sha256(user_id).hex()[:16]`, so no
user text ever reaches a path. Bytes are per user: two users uploading the same file each get a
copy. Writes go to a temp file in the target directory and are renamed into place, so a reader
never sees a partial blob.
"""

from __future__ import annotations

import contextlib
import hashlib
import os
import re
import tempfile
from collections.abc import Iterator
from pathlib import Path
from typing import BinaryIO

CHUNK_BYTES = 1024 * 1024  # the Storage port promises chunks of at most 1 MiB

_SHA256 = re.compile(r"[0-9a-f]{64}")


class DiskStorage:
    def __init__(self, root: str | os.PathLike[str]) -> None:
        self.root = Path(root)

    def _locator(self, user_id: str, sha256: str) -> str:
        if not _SHA256.fullmatch(sha256):
            raise ValueError(f"not a lowercase sha256 hex digest: {sha256!r}")
        owner = hashlib.sha256(user_id.encode()).hexdigest()[:16]
        return f"{owner}/{sha256[:2]}/{sha256}"

    def _path(self, user_id: str, sha256: str) -> Path:
        return self.root / self._locator(user_id, sha256)

    def put(
        self, user_id: str, sha256: str, stream: BinaryIO, *, mime: str, size_bytes: int
    ) -> str:
        """Write the bytes and return the locator. Idempotent: existing bytes are left alone."""
        locator = self._locator(user_id, sha256)
        target = self.root / locator
        if target.is_file():
            return locator
        target.parent.mkdir(parents=True, exist_ok=True)
        written = 0
        fd, tmp_name = tempfile.mkstemp(dir=target.parent, prefix=".tmp-")
        try:
            with os.fdopen(fd, "wb") as out:
                while chunk := stream.read(CHUNK_BYTES):
                    out.write(chunk)
                    written += len(chunk)
                out.flush()
                os.fsync(out.fileno())
            if written != size_bytes:
                raise ValueError(f"expected {size_bytes} bytes for {sha256}, got {written}")
            os.replace(tmp_name, target)
        except BaseException:
            with contextlib.suppress(FileNotFoundError):
                os.unlink(tmp_name)
            raise
        return locator

    def open(self, user_id: str, sha256: str) -> Iterator[bytes]:
        """Yield the bytes in chunks of at most 1 MiB. Raises LookupError when absent.

        The file is opened here, not on the first `next()`, so a missing blob fails the call.
        """
        try:
            handle = self._path(user_id, sha256).open("rb")
        except FileNotFoundError:
            raise LookupError(f"no stored bytes for {sha256}") from None
        return self._chunks(handle)

    @staticmethod
    def _chunks(handle: BinaryIO) -> Iterator[bytes]:
        with handle:
            while chunk := handle.read(CHUNK_BYTES):
                yield chunk

    def delete(self, user_id: str, sha256: str) -> None:
        with contextlib.suppress(FileNotFoundError):
            self._path(user_id, sha256).unlink()
