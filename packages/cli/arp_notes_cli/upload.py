"""Attachment upload: upload-url, then raw PUT with no Bearer (A.4).

Owner: CLI-b ga-mxal.36.

`POST /attachments/upload-url` goes through `NotesClient.request` (Bearer). The ticket URL it
returns is the credential for the PUT, so the PUT uses a bare httpx call and never sends the token.
"""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import Any

import httpx

from arp_notes_cli.client import ClientError, NotesClient

PUT_TIMEOUT_S = 120.0

# A fixed table, not the platform's mimetypes database: the same file gets the same mime on every
# machine, and the host's allowlist (capabilities.mime_allowlist) is matched against these strings.
MIME_BY_EXTENSION = {
    ".avif": "image/avif",
    ".bmp": "image/bmp",
    ".gif": "image/gif",
    ".jpeg": "image/jpeg",
    ".jpg": "image/jpeg",
    ".png": "image/png",
    ".svg": "image/svg+xml",
    ".webp": "image/webp",
    ".flac": "audio/flac",
    ".m4a": "audio/mp4",
    ".mp3": "audio/mpeg",
    ".ogg": "audio/ogg",
    ".wav": "audio/wav",
    ".3gp": "audio/3gpp",
    ".mkv": "video/x-matroska",
    ".mov": "video/quicktime",
    ".mp4": "video/mp4",
    ".ogv": "video/ogg",
    ".webm": "video/webm",
    ".pdf": "application/pdf",
}
DEFAULT_MIME = "application/octet-stream"


def mime_for(filename: str) -> str:
    return MIME_BY_EXTENSION.get(PurePosixPath(filename).suffix.lower(), DEFAULT_MIME)


def put_bytes(upload_url: str, data: bytes, mime: str) -> dict[str, Any]:
    """PUT the raw bytes to a ticket URL. No Authorization header: the URL is the credential."""
    try:
        response = httpx.put(
            upload_url,
            content=data,
            headers={"Content-Type": mime, "Content-Length": str(len(data))},
            timeout=PUT_TIMEOUT_S,
        )
    except httpx.HTTPError as exc:
        raise ClientError(f"cannot reach the upload URL: {exc}") from exc
    if response.status_code != 201:
        try:
            body = response.json()
        except ValueError:
            body = None
        detail = body.get("error") if isinstance(body, dict) else None
        raise ClientError(
            f"upload PUT -> HTTP {response.status_code}: {detail or response.text.strip()[:200]}",
            status=response.status_code,
            body=body,
        )
    try:
        return response.json()
    except ValueError as exc:
        raise ClientError("upload PUT returned a non-JSON body") from exc


def ensure_blob(client: NotesClient, *, sha256: str, mime: str, filename: str, data: bytes) -> bool:
    """Make sure the host holds `data`. Returns True when bytes were sent, False if it had them."""
    ticket = client.request(
        "POST",
        "/attachments/upload-url",
        json={"sha256": sha256, "mime": mime, "size_bytes": len(data), "filename": filename},
    )
    status = ticket.get("status") if isinstance(ticket, dict) else None
    if status == "exists":
        return False
    if status != "upload" or not ticket.get("upload_url"):
        raise ClientError(f"unexpected upload-url answer for {filename}: {ticket!r}")
    put_bytes(ticket["upload_url"], data, mime)
    return True
