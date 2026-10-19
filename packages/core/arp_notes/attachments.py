"""Blob registry behind the Storage port, upload tickets, HMAC signed URLs.

Owner: C2 (ga-mxal.9).
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any, BinaryIO

from arp_notes.config import HostConfig


def request_upload(
    cfg: HostConfig, user_id: str, sha256: str, mime: str, size_bytes: int, filename: str
) -> dict[str, Any]:
    """-> {status:'exists', blob_id} | {status:'upload', upload_url, method:'PUT', expires_at}."""
    raise NotImplementedError("C2: attachments.request_upload")


def consume_upload(
    cfg: HostConfig, token: str, stream: BinaryIO, content_type: str, content_length: int
) -> dict[str, Any]:
    """-> {blob_id, sha256}. Public (no Bearer): the single-use ticket is the credential."""
    raise NotImplementedError("C2: attachments.consume_upload")


def content_url(cfg: HostConfig, user_id: str, blob_id: int) -> str:
    raise NotImplementedError("C2: attachments.content_url")


def open_content(cfg: HostConfig, blob_id: int, exp: int, sig: str) -> tuple[str, Iterator[bytes]]:
    """-> (mime, chunks). Raises on a bad or expired signature."""
    raise NotImplementedError("C2: attachments.open_content")


def refcounts(cfg: HostConfig, user_id: str) -> dict[int, int]:
    """blob_id -> number of note_attachments rows referencing it."""
    raise NotImplementedError("C2: attachments.refcounts")
