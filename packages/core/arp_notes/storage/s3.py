"""S3 Storage adapter, behind the optional `s3` extra. Owner: C2b (ga-mxal.26).

Install it with `pip install arp-notes-core[s3]`.

Key layout (K§12.1): `<prefix><h>/<sha256[:2]>/<sha256>` with `h = sha256(user_id).hex()[:16]`, so
no user text ever reaches a key. Bytes are per user: two users uploading the same file each get an
object.

boto3 is imported on first use, so importing this module needs no extra. Pass `client` to reuse the
host's own boto3 S3 client (credentials, region, endpoint); without one the adapter builds
`boto3.client("s3")` on first use from the standard credential chain.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterator
from typing import Any, BinaryIO

CHUNK_BYTES = 1024 * 1024  # the Storage port promises chunks of at most 1 MiB

_SHA256 = re.compile(r"[0-9a-f]{64}")
_MISSING = {"404", "NoSuchKey", "NotFound"}


def _is_missing(error: Exception) -> bool:
    response = getattr(error, "response", None) or {}
    return str(response.get("Error", {}).get("Code")) in _MISSING


class _CountingReader:
    """Wrap a stream so `put` can check the byte count after the upload."""

    def __init__(self, stream: BinaryIO) -> None:
        self._stream = stream
        self.count = 0

    def read(self, size: int = -1) -> bytes:
        chunk = self._stream.read(size)
        self.count += len(chunk)
        return chunk


class S3Storage:
    def __init__(self, bucket: str, prefix: str = "", *, client: Any = None) -> None:
        self._bucket = bucket
        self._prefix = prefix
        self._client = client

    @property
    def client(self) -> Any:
        if self._client is None:
            import boto3  # optional extra; imported here so the module imports without it

            self._client = boto3.client("s3")
        return self._client

    def _key(self, user_id: str, sha256: str) -> str:
        if not _SHA256.fullmatch(sha256):
            raise ValueError(f"not a lowercase sha256 hex digest: {sha256!r}")
        owner = hashlib.sha256(user_id.encode()).hexdigest()[:16]
        return f"{self._prefix}{owner}/{sha256[:2]}/{sha256}"

    def put(
        self, user_id: str, sha256: str, stream: BinaryIO, *, mime: str, size_bytes: int
    ) -> str:
        """Upload the bytes and return the object key.

        Idempotent: an existing object is left alone and the stream is not read.
        """
        key = self._key(user_id, sha256)
        try:
            self.client.head_object(Bucket=self._bucket, Key=key)
            return key
        except Exception as error:
            if not _is_missing(error):
                raise
        counted = _CountingReader(stream)
        # upload_fileobj reads in chunks and goes multipart for large bodies; nothing is buffered
        # whole.
        self.client.upload_fileobj(counted, self._bucket, key, ExtraArgs={"ContentType": mime})
        if counted.count != size_bytes:
            self.client.delete_object(Bucket=self._bucket, Key=key)
            raise ValueError(f"expected {size_bytes} bytes for {sha256}, got {counted.count}")
        return key

    def open(self, user_id: str, sha256: str) -> Iterator[bytes]:
        """Yield the bytes in chunks of at most 1 MiB. Raises LookupError when absent.

        The object is requested here, not on the first `next()`, so a missing blob fails the call.
        """
        key = self._key(user_id, sha256)
        try:
            body = self.client.get_object(Bucket=self._bucket, Key=key)["Body"]
        except Exception as error:
            if _is_missing(error):
                raise LookupError(f"no stored bytes for {sha256}") from None
            raise
        return self._chunks(body)

    @staticmethod
    def _chunks(body: Any) -> Iterator[bytes]:
        try:
            yield from body.iter_chunks(CHUNK_BYTES)
        finally:
            body.close()

    def delete(self, user_id: str, sha256: str) -> None:
        """Remove the object. Idempotent: S3 treats deleting an absent key as success."""
        key = self._key(user_id, sha256)  # validate before a client is ever built
        self.client.delete_object(Bucket=self._bucket, Key=key)
