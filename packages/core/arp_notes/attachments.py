"""Blob registry behind the Storage port, upload tickets, HMAC signed URLs.

Owner: C2 (ga-mxal.9). ADR §3.3, A.4, D7, D12; K§12.1.

Flow (A.4): `request_upload` checks the host policy and either reports an existing blob or issues
a single-use ticket; `consume_upload` is the public PUT behind that ticket. Reads go the other
way: `content_url` signs `/attachments/{id}/content?exp=&sig=` and `open_content` verifies it.
Bytes live behind `cfg.storage`, keyed by (user_id, sha256); the `blobs` row keeps the locator.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import tempfile
import time
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any, BinaryIO

from arp_notes import repo
from arp_notes.config import HostConfig

CHUNK_BYTES = 1024 * 1024  # most the core holds in memory at once, reading or writing a body

_SHA256 = re.compile(r"[0-9a-f]{64}")

# ---------------------------------------------------------------------------------------------
# Errors (same status/code/body shape as every other core failure)
# ---------------------------------------------------------------------------------------------


class AttachmentsDisabled(repo.NotesError):
    """Policy.attachments is off. The body is exactly {"error": "attachments_disabled"}."""

    status = 403
    code = "attachments_disabled"


class UnsupportedMime(repo.NotesError):
    status = 415
    code = "unsupported_media_type"


class AttachmentTooLarge(repo.NotesError):
    status = 413
    code = "payload_too_large"


class HashMismatch(repo.NotesError):
    """The body is not the bytes the ticket was issued for (wrong sha256 or wrong size)."""

    status = 409
    code = "hash_mismatch"


class InvalidUpload(repo.NotesError):
    status = 422
    code = "invalid_upload"


class UploadNotFound(repo.NotesError):
    """Unknown, consumed or expired ticket. One answer for all three, so a token reveals nothing."""

    status = 404
    code = "not_found"


class InvalidSignature(repo.NotesError):
    """Bad signature, or a blob id that does not exist (the two are indistinguishable)."""

    status = 403
    code = "invalid_signature"


class ExpiredSignature(repo.NotesError):
    status = 403
    code = "expired_signature"


class BlobNotFound(repo.NotesError, LookupError):
    """The blob is registered and the signature is good, but the Storage port has no bytes."""

    status = 404
    code = "not_found"


# ---------------------------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------------------------


def _now() -> float:
    return time.time()


def _utcnow() -> datetime:
    """Naive UTC, which is how upload_tickets.expires_at (TIMESTAMP) is written and compared."""
    return datetime.now(UTC).replace(tzinfo=None)


def _normalise_mime(mime: str) -> str:
    return mime.split(";", 1)[0].strip().lower()


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _check_policy(cfg: HostConfig, mime: str, size_bytes: int) -> None:
    policy = cfg.policy
    if not policy.attachments:
        raise AttachmentsDisabled()
    if policy.mime_allowlist is not None and mime not in {
        _normalise_mime(allowed) for allowed in policy.mime_allowlist
    }:
        raise UnsupportedMime(f"{mime} is not accepted here")
    if size_bytes > policy.max_attachment_bytes:
        raise AttachmentTooLarge(limit_bytes=policy.max_attachment_bytes)


def _signature(cfg: HostConfig, user_id: str, blob_id: int, exp: int) -> str:
    secret = cfg.signer.secret
    key = secret.encode() if isinstance(secret, str) else bytes(secret)
    message = f"{user_id}:{blob_id}:{exp}".encode()
    return hmac.new(key, message, hashlib.sha256).hexdigest()


# ---------------------------------------------------------------------------------------------
# Upload (A.4)
# ---------------------------------------------------------------------------------------------


def request_upload(
    cfg: HostConfig, user_id: str, sha256: str, mime: str, size_bytes: int, filename: str
) -> dict[str, Any]:
    """-> {status:'exists', blob_id} | {status:'upload', upload_url, method:'PUT', expires_at}.

    Policy comes first, so a host with attachments off answers 403 even for a known hash. The
    ticket is 32 url-safe random bytes, stored only as a sha256, bound to this user, hash, mime
    and size, and good for `Policy.upload_ticket_ttl_s` (15 minutes by default).
    """
    if not _SHA256.fullmatch(sha256):
        raise InvalidUpload("sha256 must be 64 lowercase hex characters")
    if size_bytes < 0:
        raise InvalidUpload("size_bytes must not be negative")
    mime = _normalise_mime(mime)
    _check_policy(cfg, mime, size_bytes)

    existing = repo.get_blob_by_sha256(cfg, user_id, sha256)
    if existing is not None:
        return {"status": "exists", "blob_id": existing["id"]}

    token = secrets.token_urlsafe(32)
    expires_at = (_utcnow() + timedelta(seconds=cfg.policy.upload_ticket_ttl_s)).replace(
        microsecond=0
    )
    repo.create_ticket(
        cfg,
        user_id,
        token_hash=_hash_token(token),
        sha256=sha256,
        mime=mime,
        size_bytes=size_bytes,
        filename=filename,
        expires_at=expires_at,
    )
    return {
        "status": "upload",
        "upload_url": f"/attachments/upload/{token}",
        "method": "PUT",
        "expires_at": expires_at.isoformat(),
    }


def consume_upload(
    cfg: HostConfig, token: str, stream: BinaryIO, content_type: str, content_length: int
) -> dict[str, Any]:
    """-> {blob_id, sha256}. Public (no Bearer): the single-use ticket is the credential.

    Unknown, consumed or expired ticket -> 404. Header problems (Content-Type other than the
    ticket's mime, Content-Length over its size; a negative length means "unknown") are refused
    before the ticket is spent. Past that point the ticket is spent, so a body that turns out
    wrong (409 hash_mismatch, 413) needs a fresh ticket.

    The body is spooled to a temp file one chunk at a time while it is hashed, never held whole in
    memory, and nothing is stored until the sha256 and size match the ticket. Then the bytes go
    to `cfg.storage` and the `blobs` row (storage_path = the locator it returned) is written in
    one transaction. Storage is per (user, sha256), so the same file from two users is two blobs.
    """
    ticket = repo.get_ticket(cfg, _hash_token(token))
    if ticket is None or ticket["consumed_at"] is not None or ticket["expires_at"] <= _utcnow():
        raise UploadNotFound()
    user_id: str = ticket["user_id"]
    digest: str = ticket["sha256"]
    mime: str = ticket["mime"]
    size: int = ticket["size_bytes"]

    _check_policy(cfg, mime, size)
    if content_type and _normalise_mime(content_type) != mime:
        raise UnsupportedMime(f"this ticket is for {mime}")
    if content_length > size:
        raise AttachmentTooLarge(limit_bytes=size)

    if not repo.consume_ticket(cfg, ticket["id"]):
        raise UploadNotFound()  # lost a race with another PUT on the same ticket

    known = repo.get_blob_by_sha256(cfg, user_id, digest)
    if known is not None:
        return {"blob_id": known["id"], "sha256": digest}

    hasher = hashlib.sha256()
    total = 0
    with tempfile.TemporaryFile() as spool:
        while chunk := stream.read(CHUNK_BYTES):
            total += len(chunk)
            if total > size:
                raise AttachmentTooLarge(limit_bytes=size)
            hasher.update(chunk)
            spool.write(chunk)
        if total != size:
            raise HashMismatch(f"expected {size} bytes, received {total}")
        if hasher.hexdigest() != digest:
            raise HashMismatch("sha256 of the body does not match the ticket")
        spool.seek(0)
        with cfg.db.transaction():
            locator = cfg.storage.put(user_id, digest, spool, mime=mime, size_bytes=size)
            blob = repo.insert_blob(
                cfg,
                user_id,
                sha256=digest,
                mime=mime,
                size_bytes=size,
                storage_path=locator,
            )
    return {"blob_id": blob["id"], "sha256": digest}


# ---------------------------------------------------------------------------------------------
# Serving (D7)
# ---------------------------------------------------------------------------------------------


def content_url(cfg: HostConfig, user_id: str, blob_id: int) -> str:
    """Signed, expiring URL for one blob: sig = HMAC-SHA256(secret, "{user_id}:{blob_id}:{exp}")."""
    exp = int(_now()) + cfg.signer.ttl_s
    return f"/attachments/{blob_id}/content?exp={exp}&sig={_signature(cfg, user_id, blob_id, exp)}"


def open_content(cfg: HostConfig, blob_id: int, exp: int, sig: str) -> tuple[str, Iterator[bytes]]:
    """-> (mime, chunks). Raises InvalidSignature / ExpiredSignature (403) or BlobNotFound (404).

    The URL carries no user, so the owner comes from the blobs row. An unknown blob id fails the
    same way as a wrong signature, so ids cannot be probed. Absent bytes surface here, before any
    chunk is yielded, so the router can still answer 404; chunks are then pulled one at a time.
    """
    rows = cfg.db.run("SELECT user_id, sha256, mime FROM blobs WHERE id = %s", [blob_id])
    if not rows:
        raise InvalidSignature()
    row = rows[0]
    expected = _signature(cfg, row["user_id"], blob_id, exp)
    if not hmac.compare_digest(expected.encode(), str(sig).encode()):
        raise InvalidSignature()
    if exp < int(_now()):
        raise ExpiredSignature()

    try:
        chunks = iter(cfg.storage.open(row["user_id"], row["sha256"]))
        first = next(chunks, None)
    except LookupError as exc:
        raise BlobNotFound(str(exc)) from exc
    return row["mime"], _replay(first, chunks)


def _replay(first: bytes | None, rest: Iterator[bytes]) -> Iterator[bytes]:
    if first is None:
        return
    yield first
    yield from rest


# ---------------------------------------------------------------------------------------------
# Refcounts (no deletion in P1)
# ---------------------------------------------------------------------------------------------


def refcounts(cfg: HostConfig, user_id: str) -> dict[int, int]:
    """blob_id -> number of note_attachments rows referencing it; unreferenced blobs map to 0."""
    rows = cfg.db.run(
        "SELECT b.id AS blob_id, COUNT(a.id) AS refs FROM blobs b"
        " LEFT JOIN note_attachments a ON a.blob_id = b.id"
        " WHERE b.user_id = %s GROUP BY b.id",
        [user_id],
    )
    return {row["blob_id"]: int(row["refs"]) for row in rows}


def unreferenced_older_than(cfg: HostConfig, user_id: str, days: int) -> list[dict[str, Any]]:
    """Blobs no note references, registered more than `days` days ago. Read-only."""
    return cfg.db.run(
        "SELECT b.id, b.sha256, b.mime, b.size_bytes, b.created_at FROM blobs b"
        " WHERE b.user_id = %s AND b.created_at < CURRENT_TIMESTAMP - make_interval(days => %s)"
        " AND NOT EXISTS (SELECT 1 FROM note_attachments a WHERE a.blob_id = b.id)"
        " ORDER BY b.id",
        [user_id, days],
    )
