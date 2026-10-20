"""attachments: policy, upload tickets, signed content URLs, refcounts (C2, ga-mxal.9)."""

from __future__ import annotations

import hashlib
import io
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest
from arp_notes import attachments, repo
from arp_notes.attachments import CHUNK_BYTES
from arp_notes.config import HostConfig
from arp_notes.storage.disk import DiskStorage
from arp_notes.testing.fakedb import FakeDb
from repo_support import OTHER, USER

PNG = "image/png"


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@pytest.fixture
def cfg(notes_cfg: HostConfig, tmp_path: Path) -> HostConfig:
    return replace(notes_cfg, storage=DiskStorage(tmp_path / "blobs"))


def with_policy(cfg: HostConfig, **changes: Any) -> HostConfig:
    return replace(cfg, policy=replace(cfg.policy, **changes))


def ticket_token(result: dict[str, Any]) -> str:
    assert result["status"] == "upload"
    return result["upload_url"].rsplit("/", 1)[1]


def request(cfg: HostConfig, data: bytes, user: str = USER, mime: str = PNG) -> dict[str, Any]:
    return attachments.request_upload(cfg, user, digest(data), mime, len(data), "pic.png")


def put(
    cfg: HostConfig,
    token: str,
    data: bytes,
    *,
    content_type: str = PNG,
    content_length: int | None = None,
) -> dict[str, Any]:
    length = len(data) if content_length is None else content_length
    return attachments.consume_upload(cfg, token, io.BytesIO(data), content_type, length)


def upload(cfg: HostConfig, data: bytes, user: str = USER, mime: str = PNG) -> int:
    """request + PUT; -> blob_id."""
    ticket = request(cfg, data, user, mime)
    return put(cfg, ticket_token(ticket), data, content_type=mime)["blob_id"]


def read_all(cfg: HostConfig, user: str, blob_id: int) -> tuple[str, bytes]:
    url = attachments.content_url(cfg, user, blob_id)
    query = parse_qs(urlsplit(url).query)
    mime, chunks = attachments.open_content(cfg, blob_id, int(query["exp"][0]), query["sig"][0])
    return mime, b"".join(chunks)


class CountingStream(io.BytesIO):
    """A body of `size` zero bytes that records the largest read it was asked for."""

    def __init__(self, size: int) -> None:
        super().__init__()
        self.left = size
        self.read_total = 0
        self.max_request = 0

    def read(self, size: int | None = -1) -> bytes:
        size = -1 if size is None else size
        self.max_request = max(self.max_request, size)
        n = self.left if size < 0 else min(size, self.left)
        self.left -= n
        self.read_total += n
        return b"\0" * n


# ---------------------------------------------------------------------------------------------
# request_upload
# ---------------------------------------------------------------------------------------------


def test_request_upload_issues_a_ticket(cfg: HostConfig, notes_db: FakeDb) -> None:
    data = b"first"
    result = request(cfg, data)
    assert result["status"] == "upload" and result["method"] == "PUT"
    token = ticket_token(result)
    assert result["upload_url"] == f"/attachments/upload/{token}"
    assert len(token) == 43  # 32 random bytes, url-safe base64 without padding

    expires = datetime.fromisoformat(result["expires_at"])
    assert timedelta(minutes=14) < expires - attachments._utcnow() <= timedelta(minutes=15)

    [row] = notes_db.run("SELECT * FROM upload_tickets")
    assert row["token_hash"] == hashlib.sha256(token.encode()).hexdigest()
    assert token not in str(row)  # only the hash is stored
    assert (row["user_id"], row["sha256"], row["mime"], row["size_bytes"], row["filename"]) == (
        USER,
        digest(data),
        PNG,
        len(data),
        "pic.png",
    )
    assert row["consumed_at"] is None
    assert ticket_token(request(cfg, data)) != token  # a fresh random token each time


def test_request_upload_reports_a_blob_the_user_already_has(cfg: HostConfig) -> None:
    data = b"already here"
    blob_id = upload(cfg, data)
    assert request(cfg, data) == {"status": "exists", "blob_id": blob_id}


def test_exists_is_per_user(cfg: HostConfig) -> None:
    data = b"mine alone"
    upload(cfg, data, USER)
    assert request(cfg, data, OTHER)["status"] == "upload"


def test_attachments_disabled_is_403_even_for_a_known_hash(cfg: HostConfig) -> None:
    data = b"known"
    upload(cfg, data)
    off = with_policy(cfg, attachments=False)
    with pytest.raises(attachments.AttachmentsDisabled) as excinfo:
        request(off, data)
    assert excinfo.value.status == 403
    assert excinfo.value.body == {"error": "attachments_disabled"}


def test_mime_outside_the_allowlist_is_415(cfg: HostConfig) -> None:
    pdf_only = with_policy(cfg, mime_allowlist=["application/pdf"])
    with pytest.raises(attachments.UnsupportedMime) as excinfo:
        request(pdf_only, b"png bytes", mime=PNG)
    assert excinfo.value.status == 415
    assert request(pdf_only, b"pdf bytes", mime="application/pdf")["status"] == "upload"


def test_mime_is_normalised_before_the_allowlist_and_the_ticket(
    cfg: HostConfig, notes_db: FakeDb
) -> None:
    pdf_only = with_policy(cfg, mime_allowlist=["Application/PDF"])
    result = request(pdf_only, b"pdf", mime="application/pdf; charset=binary")
    assert result["status"] == "upload"
    assert notes_db.run("SELECT mime FROM upload_tickets")[0]["mime"] == "application/pdf"


def test_no_allowlist_accepts_any_type(cfg: HostConfig) -> None:
    assert request(with_policy(cfg, mime_allowlist=None), b"odd", mime="x-odd/thing")["status"] == (
        "upload"
    )


def test_over_the_size_limit_is_413(cfg: HostConfig) -> None:
    small = with_policy(cfg, max_attachment_bytes=10)
    with pytest.raises(attachments.AttachmentTooLarge) as excinfo:
        request(small, b"x" * 11)
    assert excinfo.value.status == 413
    assert excinfo.value.body == {"error": "payload_too_large", "limit_bytes": 10}
    assert request(small, b"x" * 10)["status"] == "upload"


@pytest.mark.parametrize(
    ("sha", "size"), [("ABC", 1), ("a" * 63, 1), ("A" * 64, 1), ("a" * 64, -1)]
)
def test_malformed_requests_are_422(cfg: HostConfig, sha: str, size: int) -> None:
    with pytest.raises(attachments.InvalidUpload) as excinfo:
        attachments.request_upload(cfg, USER, sha, PNG, size, "x.png")
    assert excinfo.value.status == 422


# ---------------------------------------------------------------------------------------------
# consume_upload
# ---------------------------------------------------------------------------------------------


def test_upload_stores_the_bytes_and_registers_the_blob(cfg: HostConfig, notes_db: FakeDb) -> None:
    data = b"hello blob" * 100
    result = put(cfg, ticket_token(request(cfg, data)), data)
    assert result["sha256"] == digest(data)

    [blob] = notes_db.run("SELECT * FROM blobs")
    assert blob["id"] == result["blob_id"]
    assert (blob["user_id"], blob["mime"], blob["size_bytes"]) == (USER, PNG, len(data))
    owner = hashlib.sha256(USER.encode()).hexdigest()[:16]
    assert blob["storage_path"] == f"{owner}/{digest(data)[:2]}/{digest(data)}"  # the locator
    assert read_all(cfg, USER, blob["id"]) == (PNG, data)


def test_an_identical_pair_is_one_blob(cfg: HostConfig, notes_db: FakeDb) -> None:
    data = b"two identical screenshots"
    first = request(cfg, data)
    second = request(cfg, data)  # both tickets issued before either upload lands
    a = put(cfg, ticket_token(first), data)
    b = put(cfg, ticket_token(second), data)
    assert a == b
    assert notes_db.run("SELECT COUNT(*) AS n FROM blobs")[0]["n"] == 1
    assert request(cfg, data) == {"status": "exists", "blob_id": a["blob_id"]}


def test_two_users_uploading_identical_bytes_get_separate_blobs(
    cfg: HostConfig, notes_db: FakeDb
) -> None:
    data = b"the very same file"
    mine = upload(cfg, data, USER)
    theirs = upload(cfg, data, OTHER)
    assert mine != theirs
    rows = notes_db.run("SELECT user_id, storage_path FROM blobs ORDER BY id")
    assert [r["user_id"] for r in rows] == [USER, OTHER]
    assert rows[0]["storage_path"] != rows[1]["storage_path"]
    assert read_all(cfg, USER, mine) == (PNG, data)
    assert read_all(cfg, OTHER, theirs) == (PNG, data)


def test_hash_mismatch_is_409_and_stores_nothing(cfg: HostConfig, notes_db: FakeDb) -> None:
    data = b"what I said I would send"
    token = ticket_token(request(cfg, data))
    with pytest.raises(attachments.HashMismatch) as excinfo:
        put(cfg, token, b"what I actually sent!!!!!"[: len(data)])
    assert excinfo.value.status == 409
    assert excinfo.value.body == {"error": "hash_mismatch"}
    assert notes_db.run("SELECT COUNT(*) AS n FROM blobs")[0]["n"] == 0
    assert not (cfg.storage.root).exists()  # type: ignore[attr-defined]


def test_a_short_body_is_a_mismatch(cfg: HostConfig, notes_db: FakeDb) -> None:
    data = b"0123456789"
    token = ticket_token(request(cfg, data))
    with pytest.raises(attachments.HashMismatch):
        put(cfg, token, data[:5])
    assert notes_db.run("SELECT COUNT(*) AS n FROM blobs")[0]["n"] == 0


def test_an_oversize_body_is_413_and_is_not_read_to_the_end(
    cfg: HostConfig, notes_db: FakeDb
) -> None:
    declared = b"x" * 100
    token = ticket_token(request(cfg, declared))
    body = CountingStream(50 * CHUNK_BYTES)
    with pytest.raises(attachments.AttachmentTooLarge) as excinfo:
        attachments.consume_upload(cfg, token, body, PNG, -1)  # length unknown (chunked)
    assert excinfo.value.status == 413
    assert body.read_total <= CHUNK_BYTES  # gave up after the first chunk
    assert notes_db.run("SELECT COUNT(*) AS n FROM blobs")[0]["n"] == 0


def test_a_content_length_over_the_ticket_is_413_and_keeps_the_ticket(cfg: HostConfig) -> None:
    data = b"y" * 20
    token = ticket_token(request(cfg, data))
    with pytest.raises(attachments.AttachmentTooLarge):
        put(cfg, token, data, content_length=21)
    assert put(cfg, token, data)["sha256"] == digest(data)  # header trouble did not spend it


def test_a_different_content_type_is_415_and_keeps_the_ticket(cfg: HostConfig) -> None:
    data = b"typed"
    token = ticket_token(request(cfg, data))
    with pytest.raises(attachments.UnsupportedMime):
        put(cfg, token, data, content_type="image/jpeg")
    assert put(cfg, token, data, content_type="IMAGE/PNG; q=1")["sha256"] == digest(data)
    assert put(cfg, ticket_token(request(cfg, b"bare")), b"bare", content_type="")["blob_id"]


def test_the_body_is_streamed_in_bounded_chunks(cfg: HostConfig) -> None:
    size = 3 * CHUNK_BYTES + 5
    body = CountingStream(size)
    digester = hashlib.sha256(b"\0" * size).hexdigest()
    ticket = attachments.request_upload(cfg, USER, digester, PNG, size, "big.png")
    result = attachments.consume_upload(cfg, ticket_token(ticket), body, PNG, size)
    assert result["sha256"] == digester
    assert 0 < body.max_request <= CHUNK_BYTES
    assert body.read_total == size


def test_a_ticket_works_once(cfg: HostConfig, notes_db: FakeDb) -> None:
    data = b"replay me"
    token = ticket_token(request(cfg, data))
    put(cfg, token, data)
    with pytest.raises(attachments.UploadNotFound) as excinfo:
        put(cfg, token, data)
    assert excinfo.value.status == 404
    assert notes_db.run("SELECT consumed_at FROM upload_tickets")[0]["consumed_at"] is not None


def test_a_ticket_spent_on_a_bad_body_is_gone(cfg: HostConfig) -> None:
    data = b"bound bytes"
    token = ticket_token(request(cfg, data))
    with pytest.raises(attachments.HashMismatch):
        put(cfg, token, b"other bytes")
    with pytest.raises(attachments.UploadNotFound):
        put(cfg, token, data)


def test_an_expired_ticket_is_404(cfg: HostConfig, notes_db: FakeDb) -> None:
    data = b"too slow"
    token = ticket_token(request(cfg, data))
    notes_db.run(
        "UPDATE upload_tickets SET expires_at = %s", [attachments._utcnow() - timedelta(seconds=1)]
    )
    with pytest.raises(attachments.UploadNotFound):
        put(cfg, token, data)
    assert notes_db.run("SELECT COUNT(*) AS n FROM blobs")[0]["n"] == 0


def test_an_unknown_token_is_404(cfg: HostConfig) -> None:
    with pytest.raises(attachments.UploadNotFound):
        put(cfg, "not-a-real-token", b"x")


def test_the_ticket_lifetime_follows_the_policy(cfg: HostConfig, notes_db: FakeDb) -> None:
    short = with_policy(cfg, upload_ticket_ttl_s=60)
    result = request(short, b"quick")
    expires = datetime.fromisoformat(result["expires_at"])
    assert expires - attachments._utcnow() <= timedelta(seconds=60)


def test_losing_the_claim_race_is_404(cfg: HostConfig, monkeypatch: pytest.MonkeyPatch) -> None:
    data = b"raced"
    token = ticket_token(request(cfg, data))
    monkeypatch.setattr(repo, "consume_ticket", lambda cfg, ticket_id: False)
    with pytest.raises(attachments.UploadNotFound):
        put(cfg, token, data)


def test_attachments_switched_off_after_the_ticket_was_issued_is_403(cfg: HostConfig) -> None:
    data = b"policy flipped"
    token = ticket_token(request(cfg, data))
    with pytest.raises(attachments.AttachmentsDisabled):
        put(with_policy(cfg, attachments=False), token, data)


def test_the_blob_belongs_to_the_ticket_user(cfg: HostConfig, notes_db: FakeDb) -> None:
    data = b"whose is it"
    put(cfg, ticket_token(request(cfg, data, OTHER)), data)
    assert notes_db.run("SELECT user_id FROM blobs")[0]["user_id"] == OTHER


def test_storage_failure_rolls_back_the_blob_row(
    cfg: HostConfig, notes_db: FakeDb, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = b"storage is down"

    def boom(*args: Any, **kwargs: Any) -> str:
        raise OSError("storage unavailable")

    monkeypatch.setattr(cfg.storage, "put", boom)
    token = ticket_token(request(cfg, data))
    with pytest.raises(OSError, match="storage unavailable"):
        put(cfg, token, data)
    assert notes_db.run("SELECT COUNT(*) AS n FROM blobs")[0]["n"] == 0


# ---------------------------------------------------------------------------------------------
# content_url / open_content
# ---------------------------------------------------------------------------------------------


def signed(cfg: HostConfig, user: str, blob_id: int) -> tuple[int, str]:
    query = parse_qs(urlsplit(attachments.content_url(cfg, user, blob_id)).query)
    return int(query["exp"][0]), query["sig"][0]


def test_content_url_shape_and_signature(cfg: HostConfig, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(attachments, "_now", lambda: 1_000_000.0)
    url = attachments.content_url(cfg, USER, 7)
    assert url.startswith("/attachments/7/content?exp=1003600&sig=")  # ttl 1 h
    import hmac

    expected = hmac.new(b"test-secret", f"{USER}:7:1003600".encode(), hashlib.sha256).hexdigest()
    assert url.endswith(f"&sig={expected}")


def test_a_signed_url_serves_the_bytes_with_the_stored_mime(cfg: HostConfig) -> None:
    data = b"%PDF-1.7 pretend"
    blob_id = upload(cfg, data, mime="application/pdf")
    assert read_all(cfg, USER, blob_id) == ("application/pdf", data)


def test_a_tampered_signature_is_refused(cfg: HostConfig) -> None:
    blob_id = upload(cfg, b"guarded")
    exp, sig = signed(cfg, USER, blob_id)
    flipped = sig[:-1] + ("0" if sig[-1] != "0" else "1")
    for bad in (flipped, sig[:-2], sig.upper(), "", "é" * 64):
        with pytest.raises(attachments.InvalidSignature) as excinfo:
            attachments.open_content(cfg, blob_id, exp, bad)
        assert excinfo.value.status == 403


def test_a_tampered_expiry_is_refused(cfg: HostConfig) -> None:
    blob_id = upload(cfg, b"guarded too")
    exp, sig = signed(cfg, USER, blob_id)
    with pytest.raises(attachments.InvalidSignature):
        attachments.open_content(cfg, blob_id, exp + 3600, sig)  # extending the life breaks it


def test_an_expired_signature_is_refused(cfg: HostConfig, monkeypatch: pytest.MonkeyPatch) -> None:
    blob_id = upload(cfg, b"stale link")
    exp, sig = signed(cfg, USER, blob_id)
    monkeypatch.setattr(attachments, "_now", lambda: exp + 1)
    with pytest.raises(attachments.ExpiredSignature) as excinfo:
        attachments.open_content(cfg, blob_id, exp, sig)
    assert excinfo.value.status == 403
    monkeypatch.setattr(attachments, "_now", lambda: exp)
    mime, chunks = attachments.open_content(cfg, blob_id, exp, sig)  # still valid at exp itself
    assert (mime, b"".join(chunks)) == (PNG, b"stale link")


def test_a_signature_for_another_user_does_not_open_my_blob(cfg: HostConfig) -> None:
    data = b"private"
    mine = upload(cfg, data, USER)
    exp, sig = signed(cfg, OTHER, mine)  # OTHER signs a URL for a blob that is not theirs
    with pytest.raises(attachments.InvalidSignature):
        attachments.open_content(cfg, mine, exp, sig)


def test_a_signature_does_not_move_between_blobs(cfg: HostConfig) -> None:
    one, two = upload(cfg, b"one"), upload(cfg, b"two")
    exp, sig = signed(cfg, USER, one)
    with pytest.raises(attachments.InvalidSignature):
        attachments.open_content(cfg, two, exp, sig)


def test_an_unknown_blob_looks_like_a_bad_signature(cfg: HostConfig) -> None:
    exp, sig = signed(cfg, USER, 9999)
    with pytest.raises(attachments.InvalidSignature):
        attachments.open_content(cfg, 9999, exp, sig)


def test_the_secret_can_be_bytes(cfg: HostConfig) -> None:
    class BytesSigner:
        secret = b"test-secret"
        ttl_s = 3600

    blob_id = upload(cfg, b"bytes secret")
    exp, sig = signed(replace(cfg, signer=BytesSigner()), USER, blob_id)
    mime, chunks = attachments.open_content(cfg, blob_id, exp, sig)
    assert b"".join(chunks) == b"bytes secret"


def test_a_missing_file_on_disk_is_404(cfg: HostConfig, tmp_path: Path) -> None:
    data = b"lost from disk"
    blob_id = upload(cfg, data)
    for path in (tmp_path / "blobs").rglob(digest(data)):
        path.unlink()
    exp, sig = signed(cfg, USER, blob_id)
    with pytest.raises(attachments.BlobNotFound) as excinfo:
        attachments.open_content(cfg, blob_id, exp, sig)  # raised up front, not mid-stream
    assert excinfo.value.status == 404
    assert isinstance(excinfo.value, LookupError)


class WatchedStorage:
    """Delegates to DiskStorage and records how many chunks were pulled and how big."""

    def __init__(self, inner: DiskStorage) -> None:
        self.inner = inner
        self.pulled = 0
        self.largest = 0

    def put(self, *args: Any, **kwargs: Any) -> str:
        return self.inner.put(*args, **kwargs)

    def delete(self, user_id: str, sha256: str) -> None:
        self.inner.delete(user_id, sha256)

    def open(self, user_id: str, sha256: str):  # type: ignore[no-untyped-def]
        for chunk in self.inner.open(user_id, sha256):
            self.pulled += 1
            self.largest = max(self.largest, len(chunk))
            yield chunk


def test_a_chunked_read_never_holds_more_than_one_chunk(cfg: HostConfig) -> None:
    size = 4 * CHUNK_BYTES + 100
    data = b"\1" * size
    blob_id = upload(cfg, data)
    watched = WatchedStorage(cfg.storage)  # type: ignore[arg-type]
    watching = replace(cfg, storage=watched)

    exp, sig = signed(watching, USER, blob_id)
    mime, chunks = attachments.open_content(watching, blob_id, exp, sig)
    assert watched.pulled == 1  # primed to surface a missing blob, nothing more
    seen = 0
    for consumed, chunk in enumerate(chunks, start=1):
        seen += len(chunk)
        assert watched.pulled <= consumed + 1  # at most one chunk read ahead of the consumer
        assert len(chunk) <= CHUNK_BYTES
    assert seen == size
    assert watched.largest <= CHUNK_BYTES


def test_an_empty_blob_opens_to_no_chunks(cfg: HostConfig) -> None:
    blob_id = upload(cfg, b"")
    assert read_all(cfg, USER, blob_id) == (PNG, b"")


# ---------------------------------------------------------------------------------------------
# refcounts / unreferenced_older_than
# ---------------------------------------------------------------------------------------------


def attach(db: FakeDb, blob_id: int, ref: str, user: str = USER) -> int:
    note_id = db.run(
        "INSERT INTO notes (user_id, title) VALUES (%s, %s) RETURNING id", [user, "n"]
    )[0]["id"]
    db.run(
        "INSERT INTO note_attachments (note_id, blob_id, filename, ref_in_markdown)"
        " VALUES (%s, %s, %s, %s)",
        [note_id, blob_id, "f.png", ref],
    )
    return note_id


def test_refcounts_count_note_attachments_and_include_unreferenced(
    cfg: HostConfig, notes_db: FakeDb
) -> None:
    used_twice = upload(cfg, b"used twice")
    used_once = upload(cfg, b"used once")
    orphan = upload(cfg, b"orphan")
    theirs = upload(cfg, b"theirs", OTHER)
    attach(notes_db, used_twice, "![[a]]")
    attach(notes_db, used_twice, "![[b]]")
    attach(notes_db, used_once, "![[c]]")
    assert attachments.refcounts(cfg, USER) == {used_twice: 2, used_once: 1, orphan: 0}
    assert attachments.refcounts(cfg, OTHER) == {theirs: 0}
    assert attachments.refcounts(cfg, "nobody") == {}


def test_unreferenced_older_than_filters_by_age_and_use(cfg: HostConfig, notes_db: FakeDb) -> None:
    old_orphan = upload(cfg, b"old orphan")
    new_orphan = upload(cfg, b"new orphan")
    old_used = upload(cfg, b"old but used")
    other_user = upload(cfg, b"someone else's", OTHER)
    attach(notes_db, old_used, "![[x]]")
    notes_db.run(
        "UPDATE blobs SET created_at = CURRENT_TIMESTAMP - INTERVAL '45 days' WHERE id = ANY(%s)",
        [[old_orphan, old_used, other_user]],
    )

    found = attachments.unreferenced_older_than(cfg, USER, 30)
    assert [row["id"] for row in found] == [old_orphan]
    assert found[0]["sha256"] == digest(b"old orphan")
    assert attachments.unreferenced_older_than(cfg, USER, 60) == []
    assert [r["id"] for r in attachments.unreferenced_older_than(cfg, USER, 0)] == [
        old_orphan,
        new_orphan,
    ]
    # Read-only: nothing was deleted in P1.
    assert notes_db.run("SELECT COUNT(*) AS n FROM blobs")[0]["n"] == 4
