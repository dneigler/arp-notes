"""repo: blob registry and upload-ticket row access (C1b, ga-mxal.8; the logic is C2's)."""

from __future__ import annotations

from datetime import datetime, timedelta

from arp_notes import repo
from arp_notes.config import HostConfig
from arp_notes.testing.fakedb import FakeDb
from repo_support import (
    OTHER,
    USER,
    add_blob,
    sha,
)

DIGEST = sha("bytes")


def test_insert_blob_is_idempotent_per_user(notes_cfg: HostConfig, notes_db: FakeDb) -> None:
    first = repo.insert_blob(
        notes_cfg, USER, sha256=DIGEST, mime="image/png", size_bytes=5, storage_path="loc", width=4
    )
    again = repo.insert_blob(
        notes_cfg, USER, sha256=DIGEST, mime="image/webp", size_bytes=9, storage_path="other"
    )
    assert again == first  # the existing row wins, nothing is overwritten
    assert (first["mime"], first["size_bytes"], first["storage_path"], first["width"]) == (
        "image/png",
        5,
        "loc",
        4,
    )
    theirs = repo.insert_blob(
        notes_cfg, OTHER, sha256=DIGEST, mime="image/png", size_bytes=5, storage_path="loc"
    )
    assert theirs["id"] != first["id"]  # bytes are per user (K§12.1)


def test_blob_lookups_are_user_scoped(notes_cfg: HostConfig, notes_db: FakeDb) -> None:
    blob_id, digest = add_blob(notes_db, text="mine")
    _, theirs = add_blob(notes_db, OTHER, text="theirs")
    assert repo.get_blob(notes_cfg, USER, blob_id)["sha256"] == digest  # type: ignore[index]
    assert repo.get_blob(notes_cfg, OTHER, blob_id) is None
    assert repo.get_blob(notes_cfg, USER, 9999) is None
    assert repo.get_blob_by_sha256(notes_cfg, USER, digest)["id"] == blob_id  # type: ignore[index]
    assert repo.get_blob_by_sha256(notes_cfg, USER, theirs) is None
    assert repo.find_blob_ids(notes_cfg, USER, [digest, theirs, digest, "f" * 64]) == {
        digest: blob_id
    }
    assert repo.find_blob_ids(notes_cfg, USER, []) == {}


def test_tickets_are_single_use(notes_cfg: HostConfig) -> None:
    expires = datetime.now() + timedelta(minutes=15)
    ticket = repo.create_ticket(
        notes_cfg,
        USER,
        token_hash=sha("token"),
        sha256=DIGEST,
        mime="image/png",
        size_bytes=5,
        filename="a.png",
        expires_at=expires,
    )
    assert ticket["consumed_at"] is None and ticket["user_id"] == USER
    found = repo.get_ticket(notes_cfg, sha("token"))
    assert found is not None and found["id"] == ticket["id"]
    assert repo.get_ticket(notes_cfg, sha("unknown")) is None

    assert repo.consume_ticket(notes_cfg, ticket["id"]) is True
    assert repo.consume_ticket(notes_cfg, ticket["id"]) is False
    consumed = repo.get_ticket(notes_cfg, sha("token"))
    assert consumed is not None and consumed["consumed_at"] is not None
