"""A fake arp-notes host that can also export, for the pull tests (CLI-c, ga-mxal.37).

`ExportHost` is the sync fake plus `GET /notes/{id}/export` and the signed content route, built to
behave like core's export (C3): app-authored notes get a generated frontmatter block with an
`arp_id` and a fresh `exported_at` on every export; imported notes come back verbatim; the manifest
is the `X-Arp-Attachments` JSON header; `content_url` is a host-relative path, like the core's.
Every attachment row it sends is checked against the core's Attachment schema.
"""

from __future__ import annotations

import json
import uuid
from importlib import resources
from typing import Any

import httpx
import respx
from arp_notes_cli.upload import mime_for
from cli_support import API, sha
from jsonschema import Draft202012Validator
from sync_support import FakeHost

_ATTACHMENT = Draft202012Validator(
    json.loads(
        (resources.files("arp_notes.schemas") / "attachment.json").read_text(encoding="utf-8")
    )
)
_NAMESPACE = uuid.UUID("2f1f2f0e-6b8c-5a52-9f4e-3a0f6a5e7d11")
SIG = "ab" * 16


class ExportHost(FakeHost):
    def __init__(
        self,
        router: respx.MockRouter,
        *,
        omit_header: bool = False,
        absolute_urls: bool = False,
        export_on: bool = True,
        page_size: int = 100,
        **kwargs: Any,
    ) -> None:
        super().__init__(router, **kwargs)
        self.app_notes: dict[int, dict[str, Any]] = {}
        self.exports: list[httpx.Request] = []
        self.downloads: list[httpx.Request] = []
        self.corrupt: set[str] = set()  # sha256 whose content comes back wrong
        self.omit_header = omit_header
        self.absolute_urls = absolute_urls
        self.page_size = page_size
        self.export_count = 0
        self._blob_ids: dict[str, int] = {}
        self.caps["export"] = export_on
        router.get(url__regex=rf"{API}/notes/\d+/export(\?.*)?$").mock(side_effect=self._export)
        router.get(url__regex=rf"{API}/attachments/\d+/content(\?.*)?$").mock(
            side_effect=self._content
        )

    # -- seeding

    def add_app_note(
        self,
        title: str,
        body_md: str,
        attachments: list[tuple[str, bytes, str]] | None = None,
        kind: str = "masterclass",
    ) -> int:
        """An app-authored note; attachments are (filename, bytes, ref_in_markdown)."""
        self._next_id += 1
        specs = attachments or []
        for _, data, _ in specs:
            self.blobs[sha(data)] = data  # the host holds the bytes, as it would after the upload
        self.app_notes[self._next_id] = {
            "title": title,
            "body_md": body_md,
            "kind": kind,
            "attachments": specs,
        }
        return self._next_id

    def arp_id_of(self, note_id: int) -> str:
        return str(uuid.uuid5(_NAMESPACE, f"u:{note_id}"))

    # -- helpers

    def _blob_id(self, digest: str) -> int:
        return self._blob_ids.setdefault(digest, len(self._blob_ids) + 1)

    def _row(self, index: int, filename: str, data: bytes, ref: str) -> dict[str, Any]:
        digest = sha(data)
        blob_id = self._blob_id(digest)
        path = f"/api/v1/attachments/{blob_id}/content?exp=1792332600&sig={SIG}"
        row = {
            "id": index,
            "blob_id": blob_id,
            "filename": filename,
            "ref_in_markdown": ref,
            "mime": mime_for(filename),
            "size_bytes": len(data),
            "sha256": digest,
            "content_url": f"https://notes.example.test{path}" if self.absolute_urls else path,
        }
        _ATTACHMENT.validate(row)
        return row

    def _rows(self, note_id: int) -> list[dict[str, Any]] | None:
        if note_id in self.app_notes:
            specs = self.app_notes[note_id]["attachments"]
            return [self._row(i, *spec) for i, spec in enumerate(specs, 1)]
        for note in self.notes.values():
            if note["id"] == note_id:
                return [
                    self._row(i, a["filename"], self.blobs[a["sha256"]], a["ref_in_markdown"])
                    for i, a in enumerate(note["payload"]["attachments"], 1)
                ]
        return None

    # -- routes

    def _export(self, request: httpx.Request) -> httpx.Response:
        self._log(request)
        assert request.headers["authorization"].startswith("Bearer ")
        self.exports.append(request)
        note_id = int(request.url.path.split("/")[-2])
        rows = self._rows(note_id)
        if rows is None:
            return httpx.Response(404, json={"error": "not_found"})
        if not self.caps["export"]:
            return httpx.Response(403, json={"error": "export_disabled"})
        enrich = request.url.params.get("with_enrichment") == "true"
        style = request.url.params.get("enrichment_style", "frontmatter")
        self.export_count += 1
        stamp = f"2026-10-19T12:00:{self.export_count % 60:02d}Z"
        part = "note"
        if note_id in self.app_notes:
            note = self.app_notes[note_id]
            if enrich and style == "companion":
                text = (
                    f"---\narp_id: {self.arp_id_of(note_id)}\n"
                    f"arp_companion_for: {note['title']}\n"
                    f"exported_at: {stamp}\narp_links: []\n---\n"
                )
                part = "companion"
            else:
                head = f"arp_id: {self.arp_id_of(note_id)}\nkind: {note['kind']}\n"
                head += f"exported_at: {stamp}\n" + ("arp_links: []\n" if enrich else "")
                text = f"---\n{head}---\n{note['body_md']}"
        else:
            payload = next(n["payload"] for n in self.notes.values() if n["id"] == note_id)
            text = payload["body_md"]
            if enrich and style == "companion":
                doc = next(d for d, n in self.notes.items() if n["id"] == note_id)
                text = f"---\narp_id: {doc}\narp_companion_for: {payload['title']}\n---\n"
                part = "companion"
            elif enrich:
                text = text.replace("---\n", "---\narp_links: []\n", 1)
        headers = {"X-Arp-Export-Part": part}
        if not self.omit_header:
            headers["X-Arp-Attachments"] = json.dumps(rows, separators=(",", ":"))
        return httpx.Response(
            200,
            content=text.encode("utf-8"),
            headers={"content-type": "text/markdown; charset=utf-8", **headers},
        )

    def _content(self, request: httpx.Request) -> httpx.Response:
        self._log(request)
        self.downloads.append(request)
        blob_id = int(request.url.path.split("/")[-2])
        digest = next((d for d, b in self._blob_ids.items() if b == blob_id), None)
        if digest is None or digest not in self.blobs:
            return httpx.Response(404, json={"error": "not_found"})
        if digest in self.corrupt:
            return httpx.Response(200, content=b"not the bytes you hashed")
        return httpx.Response(200, content=self.blobs[digest])

    def _get_note(self, request: httpx.Request) -> httpx.Response:
        note_id = int(request.url.path.rsplit("/", 1)[1])
        if note_id in self.app_notes:
            self._log(request)
            note = self.app_notes[note_id]
            return httpx.Response(
                200,
                json={
                    "id": note_id,
                    "title": note["title"],
                    "origin": "app",
                    "body_md": note["body_md"],
                    "attachments": self._rows(note_id),
                },
            )
        response = super()._get_note(request)
        if response.status_code != 200:
            return response
        body = json.loads(response.content)
        payload = next(n["payload"] for n in self.notes.values() if n["id"] == note_id)
        body.update(title=payload["title"], origin="source", attachments=self._rows(note_id))
        return httpx.Response(200, json=body)

    def _list_notes(self, request: httpx.Request) -> httpx.Response:
        listing = json.loads(super()._list_notes(request).content)
        items = [
            {
                **item,
                "title": self.notes_by_id()[item["id"]]["payload"]["title"],
                "origin": "source",
            }
            for item in listing["items"]
        ]
        items += [
            {"id": nid, "title": n["title"], "origin": "app"} for nid, n in self.app_notes.items()
        ]
        origin = request.url.params.get("origin")
        if origin:
            items = [i for i in items if i["origin"] == origin]
        items.sort(key=lambda i: i["id"])
        start = int(request.url.params.get("before") or 0)
        page = items[start : start + self.page_size]
        more = start + self.page_size < len(items)
        listing.update(items=page, next_cursor=str(start + self.page_size) if more else None)
        return httpx.Response(200, json=listing)

    def notes_by_id(self) -> dict[int, dict[str, Any]]:
        return {n["id"]: n for n in self.notes.values()}
