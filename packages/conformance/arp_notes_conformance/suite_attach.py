"""Conformance: attachments and signed URLs (A.2 attachments endpoints, A.4, R§3, R§5).

Owner: C7b ga-mxal.38. Every check drives the host over HTTP only. A blob cannot be deleted over
the wire, so a run leaves the (tiny, unique) blobs it uploaded behind; a host's hygiene sweep
(`unreferenced_blobs`, K§6.2) collects them after 30 days. Notes are cleaned up as usual.

What is proved:

- upload-url -> PUT 201 -> `exists` on the second ask; the blob then shows on the note it was
  attached to, and its signed `content_url` serves the same bytes;
- hash mismatch is 409 and stores nothing; a ticket works once (replay and unknown token are 404);
  oversize is 413 (at upload-url, and as a body longer than the ticket);
- a MIME outside the allowlist is 415, and a host that declares `attachments=false` refuses
  upload-url (capabilities against behaviour);
- a paste-style app note (`attachment://<blob_id>` in `body_md`) lists the blob on create and on
  autosave, and drops it when the ref leaves the body;
- signed content: 200 for the URL as issued, 403 when the signature is altered, when `exp` is in
  the past, or when either is missing. A signature that has genuinely lapsed needs the host's
  clock, so the kit proves the refusal with an `exp` that is already past, which no signature can
  cover.
"""

from __future__ import annotations

import struct
import time
import zlib
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx

from .harness import CheckFailed, CheckSkipped, Harness, sha256_hex
from .suite_core import need, same

Check = Callable[[Harness], None]
CHECKS: list[tuple[str, Check]] = []

PNG = "image/png"
FOREIGN_MIME = "application/x-arpn-conformance"  # not on any sane allowlist


def check(name: str) -> Callable[[Check], Check]:
    def register(fn: Check) -> Check:
        CHECKS.append((name, fn))
        return fn

    return register


# -- helpers (shared with suite_export and suite_mcp) ---------------------------------------


@dataclass(frozen=True)
class Blob:
    """Bytes to upload, as a client would describe them."""

    data: bytes
    mime: str
    filename: str

    @property
    def sha256(self) -> str:
        return sha256_hex(self.data)

    @property
    def size(self) -> int:
        return len(self.data)

    def request(self) -> dict[str, Any]:
        return {
            "sha256": self.sha256,
            "mime": self.mime,
            "size_bytes": self.size,
            "filename": self.filename,
        }

    def upsert_entry(self) -> dict[str, Any]:
        return {
            "sha256": self.sha256,
            "filename": self.filename,
            "mime": self.mime,
            "size_bytes": self.size,
            "ref_in_markdown": self.filename,
        }

    @property
    def embed(self) -> str:
        return f"![[{self.filename}]]"


def tiny_png(salt: str) -> bytes:
    """A valid 1x1 PNG whose bytes (and so sha256) are unique to `salt`."""

    def chunk(kind: bytes, data: bytes) -> bytes:
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    header = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    pixels = zlib.compress(b"\x00\xff\x00\x00")
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"tEXt", b"Comment\x00" + salt.encode())
        + chunk(b"IDAT", pixels)
        + chunk(b"IEND", b"")
    )


def attachments_on(h: Harness) -> None:
    """Skip the check when the host declares it takes no attachments."""
    if not h.capabilities["attachments"]:
        raise CheckSkipped("the host declares attachments=false (see attachments.refused_when_off)")


def accepted_mime(h: Harness) -> str:
    """image/png when the host takes it, else the first plain type on its allowlist."""
    allow = h.capabilities["mime_allowlist"]
    if allow is None:
        return PNG
    exact = [m for m in allow if "*" not in m]
    if PNG in (m.casefold() for m in exact):
        return PNG
    if exact:
        return exact[0]
    raise CheckSkipped(f"cannot pick a MIME type from the allowlist {allow}")


def new_blob(h: Harness, label: str, *, extra: int = 0) -> Blob:
    """A blob nobody uploaded before: its bytes carry this check's tag."""
    mime = accepted_mime(h)
    salt = f"{h.tag}-{label}"
    data = tiny_png(salt) if mime == PNG else f"arpn-conformance {salt}".encode()
    if extra:
        data += b"\x00" * extra
    ext = {"image/png": "png", "application/pdf": "pdf"}.get(mime, "bin")
    return Blob(data, mime, f"{label}-{h.tag}.{ext}")


def ask_upload(h: Harness, blob: Blob) -> dict[str, Any]:
    return h.call("POST", "/attachments/upload-url", shape="UploadUrlResult", json=blob.request())


def put_bytes(
    h: Harness, url: str, data: bytes, mime: str, *, content_type: str | None = None
) -> httpx.Response:
    """The public PUT: no Authorization header, the URL is the credential (A.4)."""
    return h.client.request(
        "PUT", url, content=data, headers={"Content-Type": content_type or mime}
    )


def ticket(h: Harness, blob: Blob) -> str:
    """The upload URL of a fresh ticket for `blob`."""
    answer = ask_upload(h, blob)
    same(answer["status"], "upload", f"upload-url for new bytes ({blob.filename})")
    same(answer["method"], "PUT", "upload-url method")
    need(bool(answer.get("upload_url")), "upload-url answered `upload` without an upload_url")
    need(bool(answer.get("expires_at")), "upload-url answered `upload` without expires_at")
    return answer["upload_url"]


def upload(h: Harness, blob: Blob) -> int:
    """The whole A.4 step 2: ask, PUT, check the 201. Returns the blob id."""
    answer = ask_upload(h, blob)
    if answer["status"] == "exists":
        return int(answer["blob_id"])
    response = put_bytes(h, answer["upload_url"], blob.data, blob.mime)
    h.expect_status(response, 201, f"PUT {blob.filename}")
    body = h.decode(response, "PUT upload")
    h.schemas.validate("UploadResult", body, "PUT upload response")
    same(body["sha256"], blob.sha256, "sha256 echoed by the PUT")
    return int(body["blob_id"])


def upsert_with(
    h: Harness, label: str, blobs: list[Blob], *, path: str | None = None, **over: Any
) -> tuple[int, dict[str, Any]]:
    """Upsert the scratch document with an embed of every blob; -> (note_id, UpsertResult)."""
    doc = h.fixture.doc("scratch")
    body = doc.body + "\n" + "\n".join(b.embed for b in blobs) + "\n"
    return h.upsert(
        doc,
        label=label,
        body=body,
        path=path or f"Scratch/{label}.md",
        attachments=[b.upsert_entry() for b in blobs],
        **over,
    )


def signed(url: str) -> tuple[str, dict[str, str]]:
    """A signed URL as (URL without its query, query parameters)."""
    parts = urlsplit(url)
    return urlunsplit(parts._replace(query="", fragment="")), dict(parse_qsl(parts.query))


def fetch(h: Harness, base: str, query: dict[str, str]) -> httpx.Response:
    """GET a content URL as a browser would: no Authorization header."""
    return h.client.get(base + ("?" + urlencode(query) if query else ""))


def content_url_of(h: Harness, blob_id: int) -> str:
    meta = h.call("GET", f"/attachments/{blob_id}", shape="Attachment")
    same(meta["blob_id"], blob_id, "GET /attachments/{id} blob_id")
    return meta["content_url"]


def readable(h: Harness, content_url: str, blob: Blob) -> httpx.Response:
    """GET a content URL, require 200 and the blob's bytes."""
    response = h.client.get(content_url)
    h.expect_status(response, 200, f"GET {blob.filename} content_url")
    same(response.content, blob.data, f"bytes served for {blob.filename}")
    return response


# -- checks ---------------------------------------------------------------------------------


@check("attachments.upload_roundtrip")
def upload_roundtrip(h: Harness) -> None:
    attachments_on(h)
    blob = new_blob(h, "shot")
    first = ask_upload(h, blob)
    same(first["status"], "upload", "first upload-url for new bytes")
    same(first["method"], "PUT", "upload method")

    put = put_bytes(h, first["upload_url"], blob.data, blob.mime)
    h.expect_status(put, 201, "PUT upload")
    body = h.decode(put, "PUT upload")
    h.schemas.validate("UploadResult", body, "PUT upload response")
    same(body["sha256"], blob.sha256, "sha256 of the stored bytes")

    again = ask_upload(h, blob)
    same((again["status"], again.get("blob_id")), ("exists", body["blob_id"]), "second upload-url")

    note_id, result = upsert_with(h, "attached", [blob])
    same((result["outcome"], result["missing_attachments"]), ("created", []), "upsert")
    note = h.get_note(note_id)
    same(len(note["attachments"]), 1, "attachments on the note")
    attachment = note["attachments"][0]
    same(
        (attachment["sha256"], attachment["size_bytes"], attachment["blob_id"]),
        (blob.sha256, blob.size, body["blob_id"]),
        "attachment fields",
    )
    same(attachment["ref_in_markdown"], blob.filename, "attachment ref_in_markdown")
    same(attachment["mime"], blob.mime, "attachment mime")
    served = readable(h, attachment["content_url"], blob)
    need(
        served.headers.get("content-type", "").split(";")[0].strip().casefold() == blob.mime,
        f"content served as {served.headers.get('content-type')!r}, expected {blob.mime}",
    )
    need(
        "private" in served.headers.get("cache-control", ""),
        "attachment content must be `Cache-Control: private` (a signed URL is a credential)",
    )
    meta = h.call("GET", f"/attachments/{body['blob_id']}", shape="Attachment")
    same(meta["sha256"], blob.sha256, "GET /attachments/{id} sha256")

    listed = h.list_notes(q=h.tag, origin="source", limit=100)["items"]
    row = next(i for i in listed if i["id"] == note_id)
    same(row["attachment_count"], 1, "attachment_count on the list row")


@check("attachments.missing_blob_reported")
def missing_blob_reported(h: Harness) -> None:
    attachments_on(h)
    blob = new_blob(h, "late")
    doc = h.fixture.doc("scratch")
    body = h.upsert_body(
        doc,
        label="late",
        body=doc.body + f"\n{blob.embed}\n",
        attachments=[blob.upsert_entry()],
    )
    response = h.send("POST", "/notes/sync/upsert", json=body)
    if response.status_code == 409:  # R§6: a host may answer blob_missing instead of 200
        error = h.decode(response, "POST /notes/sync/upsert")
        h.schemas.validate("ErrorBody", error, "upsert error body")
        same(error.get("error"), "blob_missing", "error of a 409 upsert")
        same(error.get("missing"), [blob.sha256], "missing of a 409 blob_missing")
    else:
        h.expect_status(response, 200, "POST /notes/sync/upsert")
        result = h.decode(response, "POST /notes/sync/upsert")
        h.schemas.validate("UpsertResult", result, "upsert response")
        h.track(result["note_id"])
        same(result["missing_attachments"], [blob.sha256], "missing_attachments before the upload")

    upload(h, blob)  # the A.4 repair: upload, then upsert again (idempotent)
    note_id, fixed = h.upsert(
        doc,
        label="late",
        body=doc.body + f"\n{blob.embed}\n",
        path=f"Scratch/{h.tag}.md",
        attachments=[blob.upsert_entry()],
    )
    same(fixed["missing_attachments"], [], "missing_attachments after the upload")
    same([a["sha256"] for a in h.get_note(note_id)["attachments"]], [blob.sha256], "attachments")


@check("attachments.hash_mismatch")
def hash_mismatch(h: Harness) -> None:
    attachments_on(h)
    blob = new_blob(h, "claimed")
    other = new_blob(h, "actual")
    if len(other.data) != len(blob.data):  # same length: only the hash differs
        other = Blob(other.data[: len(blob.data)].ljust(len(blob.data), b"\x00"), blob.mime, "x")
    need(other.sha256 != blob.sha256, "the kit built two identical blobs")

    url = ticket(h, blob)
    wrong = put_bytes(h, url, other.data, blob.mime)
    h.expect_status(wrong, 409, "PUT of the wrong bytes")
    same(h.decode(wrong, "PUT")["error"], "hash_mismatch", "error of a wrong-hash PUT")

    short = ticket(h, new_blob(h, "claimed-long", extra=8))
    cut = put_bytes(h, short, new_blob(h, "claimed-long").data, blob.mime)
    h.expect_status(cut, 409, "PUT of fewer bytes than the ticket's size_bytes")
    same(h.decode(cut, "PUT")["error"], "hash_mismatch", "error of a wrong-size PUT")

    same(ask_upload(h, blob)["status"], "upload", "a refused PUT must not register the blob")


@check("attachments.ticket_single_use")
def ticket_single_use(h: Harness) -> None:
    attachments_on(h)
    blob = new_blob(h, "once")
    url = ticket(h, blob)
    h.expect_status(put_bytes(h, url, blob.data, blob.mime), 201, "first PUT")
    h.expect_status(put_bytes(h, url, blob.data, blob.mime), 404, "replay of a consumed ticket")

    base, _ = signed(url)
    bogus = base.rsplit("/", 1)[0] + f"/arpn-no-such-ticket-{h.tag}"
    h.expect_status(put_bytes(h, bogus, blob.data, blob.mime), 404, "PUT to an unknown ticket")


@check("attachments.oversize")
def oversize(h: Harness) -> None:
    attachments_on(h)
    limit = h.capabilities["limits"]["max_attachment_bytes"]
    blob = new_blob(h, "huge")
    big = {**blob.request(), "size_bytes": limit + 1}
    h.fails("POST", "/attachments/upload-url", 413, json=big)

    small = new_blob(h, "ticketed")
    url = ticket(h, small)
    long_body = put_bytes(h, url, small.data + b"\x00", small.mime)
    h.expect_status(long_body, 413, "PUT of more bytes than the ticket allows")
    same(ask_upload(h, small)["status"], "upload", "a refused PUT must not register the blob")


@check("attachments.mime_allowlist")
def mime_allowlist(h: Harness) -> None:
    attachments_on(h)
    allow = h.capabilities["mime_allowlist"]
    if allow is None:
        raise CheckSkipped("the host accepts any MIME type (mime_allowlist is null)")
    need(
        FOREIGN_MIME not in allow,
        f"the kit's probe type {FOREIGN_MIME} is on the allowlist: cannot test a refusal",
    )
    blob = new_blob(h, "foreign")
    h.fails("POST", "/attachments/upload-url", 415, json={**blob.request(), "mime": FOREIGN_MIME})
    upload(h, blob)  # and a type the host does list goes through


@check("attachments.refused_when_off")
def refused_when_off(h: Harness) -> None:
    if h.capabilities["attachments"]:
        raise CheckSkipped("the host takes attachments; only a host that declines is tested here")
    blob = Blob(tiny_png(h.tag), PNG, f"off-{h.tag}.png")
    response = h.send("POST", "/attachments/upload-url", json=blob.request())
    need(
        400 <= response.status_code < 500 or response.status_code == 501,
        f"capabilities.attachments is false but upload-url answered {response.status_code}: "
        f"{response.text[:200]}",
    )
    need(
        '"upload_url"' not in response.text,
        "capabilities.attachments is false but upload-url handed out an upload URL",
    )
    if response.headers.get("content-type", "").startswith("application/json"):
        body = h.decode(response, "POST /attachments/upload-url")
        if isinstance(body, dict) and "error" in body:
            h.schemas.validate("ErrorBody", body, "upload-url refusal")


@check("attachments.signed_content")
def signed_content(h: Harness) -> None:
    attachments_on(h)
    blob = new_blob(h, "signed")
    blob_id = upload(h, blob)
    upsert_with(h, "signed", [blob])
    url = content_url_of(h, blob_id)
    base, query = signed(url)
    need({"exp", "sig"} <= set(query), f"content_url {url!r} carries no exp and sig")

    readable(h, url, blob)
    exp = int(query["exp"])
    now = time.time()
    need(
        now - 300 < exp <= now + 3600 + 300,
        f"content_url expires at {exp}, which is not within an hour of now ({int(now)}): "
        "A.2 says a signed URL expires in at most 1 h",
    )

    flipped = query["sig"][:-1] + ("0" if query["sig"][-1] != "0" else "1")
    for what, params in (
        ("a tampered sig", {**query, "sig": flipped}),
        ("an exp already in the past", {**query, "exp": str(int(now) - 3600)}),
        ("an exp moved later than signed", {**query, "exp": str(exp + 600)}),
        ("no sig", {k: v for k, v in query.items() if k != "sig"}),
        ("no exp", {k: v for k, v in query.items() if k != "exp"}),
        ("no query at all", {}),
    ):
        response = fetch(h, base, params)
        need(
            response.status_code == 403,
            f"content URL with {what} must be refused with 403, got {response.status_code}",
        )
        need(blob.data not in response.content, f"content URL with {what} served the bytes")

    other = base.replace(f"/attachments/{blob_id}/", "/attachments/2147483000/")
    need(other != base, f"cannot derive another blob's URL from {base}")
    response = fetch(h, other, query)
    need(
        response.status_code == 403,
        f"another blob id under this signature must be 403, got {response.status_code}",
    )


@check("attachments.summary_thumbnail")
def summary_thumbnail(h: Harness) -> None:
    attachments_on(h)
    blob = new_blob(h, "thumb")
    if not blob.mime.startswith("image/"):
        raise CheckSkipped(f"the host's allowlist has no image type to thumbnail ({blob.mime})")
    upload(h, blob)
    note_id, _ = upsert_with(h, "thumb", [blob])
    rows = h.list_notes(q=h.tag, origin="source", limit=100)["items"]
    row = next((i for i in rows if i["id"] == note_id), None)
    if row is None:
        raise CheckFailed("the note with an image attachment is not listed")
    same(row["attachment_count"], 1, "attachment_count")
    url = row.get("thumbnail_url")
    need(bool(url), "a note whose first attachment is an image has no thumbnail_url (K§2)")
    readable(h, url, blob)


@check("attachments.app_note_paste")
def app_note_paste(h: Harness) -> None:
    """A pasted image in an app note.

    The editor writes `![name](attachment://<blob_id>)` into the body; the host must then list the
    blob on the note (on create and on autosave) so a client can render it.
    """
    attachments_on(h)
    blob = new_blob(h, "paste")
    blob_id = upload(h, blob)
    embed = (
        f"{'!' if blob.mime.startswith('image/') else ''}[{blob.filename}](attachment://{blob_id})"
    )
    note = h.create_note("pasted", body_md=f"typed text\n{embed}\n")
    got = [a for a in note["attachments"] if a["blob_id"] == blob_id]
    need(
        len(got) == 1,
        "POST /notes with an `attachment://<blob_id>` ref in body_md must list that blob in"
        f" `attachments` (got {note['attachments']})",
    )
    same(
        (got[0]["sha256"], got[0]["filename"], got[0]["ref_in_markdown"]),
        (blob.sha256, blob.filename, embed),
        "attachment created from the pasted ref",
    )
    readable(h, got[0]["content_url"], blob)
    same(h.get_note(note["id"])["attachments"][0]["blob_id"], blob_id, "attachment after a re-read")

    cleared = h.call(
        "PATCH",
        f"/notes/{note['id']}/autosave",
        shape="AutosaveResult",
        json={"body_md": "typed text only\n", "version": note["version"]},
    )
    need("note" in cleared, f"autosave with the current version must save (got {cleared})")
    same(cleared["note"]["attachments"], [], "attachments after the ref left the body")

    back = h.call(
        "PATCH",
        f"/notes/{note['id']}/autosave",
        shape="AutosaveResult",
        json={"body_md": f"again\n{embed}\n", "version": cleared["note"]["version"]},
    )
    same([a["blob_id"] for a in back["note"]["attachments"]], [blob_id], "autosave adds a ref")
