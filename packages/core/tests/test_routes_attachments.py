"""REST: upload tickets, the public PUT, signed content URLs, blob metadata (C3, ga-mxal.10)."""

from __future__ import annotations

import hashlib
import time
from typing import Any

import pytest
from app_ref import ALICE, API, BOB, ORIGIN, Ref, fails, ok
from arp_notes import attachments
from repo_support import attachment_ref

PNG = b"\x89PNG\r\n\x1a\n" + b"synthetic image bytes " * 8
PDF = b"%PDF-1.4 synthetic pdf bytes\n" * 4


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def ticket(
    ref: Ref, data: bytes = PNG, mime: str = "image/png", name: str = "a.png", **kw: Any
) -> dict[str, Any]:
    body = {"sha256": digest(data), "mime": mime, "size_bytes": len(data), "filename": name}
    return ok(ref.post("/attachments/upload-url", json=body, **kw), "UploadUrlResult")


def upload(ref: Ref, data: bytes = PNG, mime: str = "image/png", **kw: Any) -> dict[str, Any]:
    """Request a ticket and PUT the bytes. -> the 201 body."""
    issued = ticket(ref, data, mime)
    assert issued["status"] == "upload"
    return ok(
        ref.client.put(issued["upload_url"], content=data, headers={"Content-Type": mime}),
        "UploadResult",
        201,
    )


def attach_to_note(ref: Ref, data: bytes = PNG, doc: str = "d1") -> dict[str, Any]:
    from repo_support import upsert_body

    upload(ref, data)
    payload = upsert_body(
        doc,
        attachments=[
            attachment_ref(digest(data), "![[a.png]]", "a.png")
            | {"mime": "image/png", "size_bytes": len(data)}
        ],
    ).model_dump(mode="json", exclude_none=True)
    result = ok(ref.post("/notes/sync/upsert", json=payload), "UpsertResult")
    assert result["missing_attachments"] == []
    return ok(ref.get(f"/notes/{result['note_id']}"), "Note")


# -- upload-url -----------------------------------------------------------------------------


def test_upload_url_issues_a_mounted_one_shot_url(ref: Ref) -> None:
    issued = ticket(ref)
    assert issued["status"] == "upload" and issued["method"] == "PUT"
    assert issued["upload_url"].startswith(f"{ORIGIN}{API}/attachments/upload/")
    assert issued["expires_at"] and "blob_id" not in issued


def test_upload_url_says_exists_for_known_bytes(ref: Ref) -> None:
    done = upload(ref)
    again = ticket(ref)
    assert again == {"status": "exists", "blob_id": done["blob_id"]}


def test_upload_url_enforces_the_policy(ref: Ref) -> None:
    body = {"sha256": digest(PNG), "mime": "image/png", "size_bytes": len(PNG), "filename": "a.png"}
    big = ref.with_policy(max_attachment_bytes=10)
    fails(big.post("/attachments/upload-url", json=body), 413, "payload_too_large")
    pdf_only = ref.with_policy(mime_allowlist=["application/pdf"])
    fails(pdf_only.post("/attachments/upload-url", json=body), 415, "unsupported_media_type")
    off = ref.with_policy(attachments=False)
    assert fails(off.post("/attachments/upload-url", json=body), 403, "attachments_disabled") == {
        "error": "attachments_disabled"
    }


def test_upload_url_rejects_a_bad_hash(ref: Ref) -> None:
    body = {"sha256": "abc", "mime": "image/png", "size_bytes": 3, "filename": "a.png"}
    assert ref.post("/attachments/upload-url", json=body).status_code == 422


# -- PUT (public) ---------------------------------------------------------------------------


def test_put_needs_no_bearer_and_registers_the_blob(ref: Ref) -> None:
    issued = ticket(ref)
    response = ref.client.put(
        issued["upload_url"], content=PNG, headers={"Content-Type": "image/png"}
    )
    body = ok(response, "UploadResult", 201)
    assert body["sha256"] == digest(PNG)
    row = ref.db.run("SELECT user_id, mime, size_bytes FROM blobs WHERE id = %s", [body["blob_id"]])
    assert row == [{"user_id": "u1", "mime": "image/png", "size_bytes": len(PNG)}]
    assert b"".join(ref.cfg.storage.open("u1", digest(PNG))) == PNG


def test_put_twice_on_one_ticket_is_404(ref: Ref) -> None:
    issued = ticket(ref)
    headers = {"Content-Type": "image/png"}
    ok(ref.client.put(issued["upload_url"], content=PNG, headers=headers), status=201)
    fails(ref.client.put(issued["upload_url"], content=PNG, headers=headers), 404, "not_found")


def test_put_an_unknown_token_is_404(ref: Ref) -> None:
    fails(ref.client.put(f"{API}/attachments/upload/nope", content=PNG), 404, "not_found")


def test_put_wrong_bytes_is_409_hash_mismatch(ref: Ref) -> None:
    issued = ticket(ref)
    forged = b"x" * len(PNG)
    response = ref.client.put(
        issued["upload_url"], content=forged, headers={"Content-Type": "image/png"}
    )
    fails(response, 409, "hash_mismatch")
    assert ref.db.run("SELECT 1 FROM blobs") == []


def test_put_too_many_bytes_is_413(ref: Ref) -> None:
    issued = ticket(ref)
    response = ref.client.put(
        issued["upload_url"], content=PNG + b"extra", headers={"Content-Type": "image/png"}
    )
    fails(response, 413, "payload_too_large")


def test_put_beyond_the_policy_cap_is_413_before_anything_is_stored(ref: Ref) -> None:
    issued = ticket(ref)
    small = ref.with_policy(max_attachment_bytes=16)
    response = small.client.put(
        issued["upload_url"], content=PNG, headers={"Content-Type": "image/png"}
    )
    fails(response, 413, "payload_too_large")
    assert ref.db.run("SELECT 1 FROM blobs") == []


def test_put_with_another_content_type_is_415(ref: Ref) -> None:
    issued = ticket(ref)
    response = ref.client.put(
        issued["upload_url"], content=PNG, headers={"Content-Type": "image/webp"}
    )
    fails(response, 415, "unsupported_media_type")


def test_put_after_the_host_turned_attachments_off_is_403(ref: Ref) -> None:
    issued = ticket(ref)
    off = ref.with_policy(attachments=False)
    response = off.client.put(
        issued["upload_url"], content=PNG, headers={"Content-Type": "image/png"}
    )
    fails(response, 403, "attachments_disabled")


def test_put_streams_a_body_without_content_length(ref: Ref) -> None:
    issued = ticket(ref)

    def chunks() -> Any:
        for i in range(0, len(PNG), 16):
            yield PNG[i : i + 16]

    response = ref.client.put(
        issued["upload_url"], content=chunks(), headers={"Content-Type": "image/png"}
    )
    assert ok(response, "UploadResult", 201)["sha256"] == digest(PNG)


def test_an_expired_ticket_is_404(ref: Ref, monkeypatch: pytest.MonkeyPatch) -> None:
    issued = ticket(ref)
    later = attachments._utcnow() + attachments.timedelta(hours=1)
    monkeypatch.setattr(attachments, "_utcnow", lambda: later)
    fails(ref.client.put(issued["upload_url"], content=PNG), 404, "not_found")


# -- content (public) -----------------------------------------------------------------------


def test_content_serves_the_bytes_from_the_signed_url(ref: Ref) -> None:
    note = attach_to_note(ref)
    url = note["attachments"][0]["content_url"]
    response = ref.client.get(url)  # no Authorization header: the signature is the credential
    assert response.status_code == 200 and response.content == PNG
    assert response.headers["content-type"] == "image/png"
    assert response.headers["cache-control"] == "private, max-age=3600"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert "content-security-policy" not in response.headers


def test_content_pdf_and_svg(ref: Ref) -> None:
    svg = b"<svg xmlns='http://www.w3.org/2000/svg'><script>alert(1)</script></svg>"
    upload(ref, PDF, "application/pdf")
    upload(ref, svg, "image/svg+xml")
    rows = ref.db.run("SELECT id, mime FROM blobs ORDER BY id")
    served: dict[str, Any] = {}
    for row in rows:
        url = attachments.content_url(ref.cfg, "u1", row["id"])
        served[row["mime"]] = ref.client.get(API + url)
    assert served["application/pdf"].content == PDF
    assert "content-security-policy" not in served["application/pdf"].headers
    assert (
        served["image/svg+xml"].headers["content-security-policy"] == "default-src 'none'; sandbox"
    )


def test_content_with_a_bad_signature_is_403(ref: Ref) -> None:
    note = attach_to_note(ref)
    blob_id = note["attachments"][0]["blob_id"]
    exp = int(time.time()) + 600
    for query in (
        f"exp={exp}&sig={'0' * 64}",
        f"exp={exp}",
        f"sig={'0' * 64}",
        "exp=abc&sig=x",
        "",
    ):
        fails(
            ref.client.get(f"{API}/attachments/{blob_id}/content?{query}"), 403, "invalid_signature"
        )


def test_content_signature_is_bound_to_the_expiry_and_the_blob(ref: Ref) -> None:
    note = attach_to_note(ref)
    url = note["attachments"][0]["content_url"]
    blob_id = note["attachments"][0]["blob_id"]
    path, _, query = url.partition("?")
    params = dict(p.split("=") for p in query.split("&"))
    stretched = f"{path}?exp={int(params['exp']) + 3600}&sig={params['sig']}"
    fails(ref.client.get(stretched), 403, "invalid_signature")
    other = path.replace(f"/{blob_id}/", f"/{blob_id + 1}/")
    fails(ref.client.get(f"{other}?{query}"), 403, "invalid_signature")


def test_content_past_its_expiry_is_403(ref: Ref, monkeypatch: pytest.MonkeyPatch) -> None:
    note = attach_to_note(ref)
    url = note["attachments"][0]["content_url"]
    monkeypatch.setattr(attachments, "_now", lambda: time.time() + 2 * 3600)
    fails(ref.client.get(url), 403, "expired_signature")


def test_content_for_missing_bytes_is_404(ref: Ref) -> None:
    note = attach_to_note(ref)
    ref.cfg.storage.delete("u1", digest(PNG))
    fails(ref.client.get(note["attachments"][0]["content_url"]), 404, "not_found")


def test_content_url_works_from_the_list_thumbnail(ref: Ref) -> None:
    attach_to_note(ref)
    thumb = ok(ref.get("/notes"))["items"][0]["thumbnail_url"]
    assert ref.client.get(thumb).content == PNG


# -- metadata -------------------------------------------------------------------------------


def test_meta_describes_the_blob_and_its_first_embed(ref: Ref) -> None:
    note = attach_to_note(ref)
    blob_id = note["attachments"][0]["blob_id"]
    meta = ok(ref.get(f"/attachments/{blob_id}"), "Attachment")
    assert meta["blob_id"] == blob_id and meta["sha256"] == digest(PNG)
    assert meta["mime"] == "image/png" and meta["size_bytes"] == len(PNG)
    assert meta["filename"] == "a.png" and meta["ref_in_markdown"] == "![[a.png]]"
    assert meta["id"] == note["attachments"][0]["id"]
    assert ref.client.get(meta["content_url"]).content == PNG


def test_meta_of_an_unembedded_blob(ref: Ref) -> None:
    blob = upload(ref)
    meta = ok(ref.get(f"/attachments/{blob['blob_id']}"), "Attachment")
    assert meta["id"] == blob["blob_id"] and meta["filename"] == digest(PNG)
    assert meta["ref_in_markdown"] == ""


def test_meta_is_private_to_the_owner(ref: Ref) -> None:
    blob = upload(ref)
    fails(ref.get(f"/attachments/{blob['blob_id']}", headers=BOB), 404, "not_found")
    fails(ref.get("/attachments/999"), 404, "not_found")
    assert ref.client.get(f"{API}/attachments/{blob['blob_id']}").status_code == 401


def test_two_users_keep_their_own_copy(ref: Ref) -> None:
    mine = upload(ref)
    issued = ticket(ref, headers=BOB)
    assert issued["status"] == "upload"  # Bob does not inherit Alice's blob
    theirs = ok(
        ref.client.put(issued["upload_url"], content=PNG, headers={"Content-Type": "image/png"}),
        "UploadResult",
        201,
    )
    assert theirs["blob_id"] != mine["blob_id"]
    assert ALICE != BOB
