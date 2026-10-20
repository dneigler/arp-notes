"""A fake arp-notes host for the sync/verify/tombstone tests (CLI-b, ga-mxal.36).

It behaves like A.2/A.4 and checks every request body it receives, and every answer it gives,
against the core's JSON schemas, so the CLI is tested against the wire contract and not against
what this fake happens to accept.
"""

from __future__ import annotations

import hashlib
import json
from importlib import resources
from typing import Any

import httpx
import respx
from cli_support import API, APP_URL, capabilities, manifest_page
from jsonschema import Draft202012Validator


def _schema(name: str) -> Draft202012Validator:
    root = resources.files("arp_notes.schemas") / name
    return Draft202012Validator(json.loads(root.read_text(encoding="utf-8")))


_UPSERT_BODY = _schema("note_upsert.json")
_UPSERT_RESULT = _schema("upsert_result.json")
_UPLOAD_BODY = _schema("upload_url_body.json")
_UPLOAD_RESULT = _schema("upload_url_result.json")
_UPLOAD_DONE = _schema("upload_result.json")
_TOMBSTONE_BODY = _schema("tombstone_body.json")
_TOMBSTONE_RESULT = _schema("tombstone_result.json")


class FakeHost:
    def __init__(
        self,
        router: respx.MockRouter,
        *,
        attachments: bool = True,
        missing_as_409: bool = False,
        lose_blobs_once: bool = False,
        relative_upload_url: bool = False,
    ) -> None:
        self.blobs: dict[str, bytes] = {}
        self.notes: dict[str, dict[str, Any]] = {}  # source_doc_id -> {id, payload, deleted_at}
        self.upload_requests: list[dict[str, Any]] = []
        self.puts: list[httpx.Request] = []
        self.upserts: list[dict[str, Any]] = []
        self.calls: list[str] = []  # "METHOD path" in order
        self.missing_as_409 = missing_as_409
        self.relative_upload_url = (
            relative_upload_url  # like core's presenter: a host-relative path
        )
        self.lose_blobs_once = lose_blobs_once  # first upsert claims every blob is missing
        self.fail_upsert_for: set[str] = set()  # source_path -> HTTP 500
        self.tamper_body: str | None = None  # what GET /notes/{id} returns instead of the body
        self.caps = capabilities()
        self.caps["attachments"] = attachments
        self.caps["mime_allowlist"] = None
        self._next_id = 100
        router.get(f"{API}/notes/capabilities").mock(side_effect=self._capabilities)
        router.get(f"{API}/notes/sync/manifest").mock(side_effect=self._manifest)
        router.post(f"{API}/attachments/upload-url").mock(side_effect=self._upload_url)
        router.put(url__regex=rf"{API}/attachments/upload/.+").mock(side_effect=self._put)
        router.post(f"{API}/notes/sync/upsert").mock(side_effect=self._upsert)
        router.post(f"{API}/notes/sync/tombstone").mock(side_effect=self._tombstone)
        router.get(url__regex=rf"{API}/notes/\d+$").mock(side_effect=self._get_note)
        router.get(f"{API}/notes").mock(side_effect=self._list_notes)

    # -- helpers

    def _log(self, request: httpx.Request) -> None:
        self.calls.append(f"{request.method} {request.url.path.removeprefix('/api/v1')}")

    def upload_url_calls(self) -> int:
        return sum(1 for c in self.calls if c == "POST /attachments/upload-url")

    def put_calls(self) -> int:
        return len(self.puts)

    def seed(self, doc_id: str, payload: dict[str, Any], deleted_at: str | None = None) -> int:
        self._next_id += 1
        self.notes[doc_id] = {"id": self._next_id, "payload": payload, "deleted_at": deleted_at}
        return self._next_id

    # -- routes

    def _capabilities(self, request: httpx.Request) -> httpx.Response:
        self._log(request)
        return httpx.Response(200, json=self.caps)

    def _manifest(self, request: httpx.Request) -> httpx.Response:
        self._log(request)
        workspace = request.url.params["source_workspace"]
        rows = [
            {
                "source_doc_id": doc_id,
                "source_path": n["payload"]["source_path"],
                "content_hash": n["payload"]["content_hash"],
                "attachments": sorted({a["sha256"] for a in n["payload"]["attachments"]}),
                "last_synced_at": "2026-10-18T14:30:00",
                "deleted_at": n["deleted_at"],
            }
            for doc_id, n in sorted(self.notes.items())
            if n["payload"]["source_workspace"] == workspace
        ]
        return httpx.Response(200, json=manifest_page(rows))

    def _upload_url(self, request: httpx.Request) -> httpx.Response:
        self._log(request)
        assert request.headers["authorization"].startswith("Bearer ")
        body = json.loads(request.content)
        _UPLOAD_BODY.validate(body)
        self.upload_requests.append(body)
        if body["sha256"] in self.blobs:
            answer = {"status": "exists", "blob_id": 1}
        else:
            ticket = f"/api/v1/attachments/upload/ticket-{body['sha256'][:12]}"
            answer = {
                "status": "upload",
                "blob_id": None,
                "upload_url": ticket if self.relative_upload_url else f"{APP_URL}{ticket}",
                "method": "PUT",
                "expires_at": "2026-10-18T14:45:00",
            }
        _UPLOAD_RESULT.validate(answer)
        return httpx.Response(200, json=answer)

    def _put(self, request: httpx.Request) -> httpx.Response:
        self._log(request)
        self.puts.append(request)
        sha = hashlib.sha256(request.content).hexdigest()
        self.blobs[sha] = request.content
        answer = {"blob_id": len(self.blobs), "sha256": sha}
        _UPLOAD_DONE.validate(answer)
        return httpx.Response(201, json=answer)

    def _upsert(self, request: httpx.Request) -> httpx.Response:
        self._log(request)
        payload = json.loads(request.content)
        _UPSERT_BODY.validate(payload)
        self.upserts.append(payload)
        if payload["source_path"] in self.fail_upsert_for:
            return httpx.Response(500, json={"error": "boom"})
        wanted = [a["sha256"] for a in payload["attachments"]]
        missing = list(dict.fromkeys(s for s in wanted if s not in self.blobs))
        if self.lose_blobs_once and wanted:
            self.lose_blobs_once = False
            missing = list(dict.fromkeys(wanted))
            for sha in missing:
                self.blobs.pop(sha, None)
        if missing and self.missing_as_409:
            return httpx.Response(409, json={"error": "blob_missing", "missing": missing})
        doc_id = payload["source_doc_id"]
        known = self.notes.get(doc_id)
        if missing:
            note_id = known["id"] if known else self.seed(doc_id, payload)
            if known:
                known["payload"] = payload
            answer = {
                "note_id": note_id,
                "outcome": "created" if known is None else "updated",
                "missing_attachments": missing,
            }
        elif known is None:
            answer = {
                "note_id": self.seed(doc_id, payload),
                "outcome": "created",
                "missing_attachments": [],
            }
        else:
            same = known["payload"] == payload and not known["deleted_at"]
            known["payload"], known["deleted_at"] = payload, None
            answer = {
                "note_id": known["id"],
                "outcome": "unchanged" if same else "updated",
                "missing_attachments": [],
            }
        answer["links_orphaned"] = 0
        _UPSERT_RESULT.validate(answer)
        return httpx.Response(200, json=answer)

    def _get_note(self, request: httpx.Request) -> httpx.Response:
        self._log(request)
        note_id = int(request.url.path.rsplit("/", 1)[1])
        for doc_id, n in self.notes.items():
            if n["id"] == note_id:
                p = n["payload"]
                body = p["body_md"] if self.tamper_body is None else self.tamper_body
                return httpx.Response(
                    200,
                    json={
                        "id": note_id,
                        "source_doc_id": doc_id,
                        "source_workspace": p["source_workspace"],
                        "source_path": p["source_path"],
                        "body_md": body,
                        "content_hash": p["content_hash"],
                    },
                )
        return httpx.Response(404, json={"error": "not_found"})

    def _list_notes(self, request: httpx.Request) -> httpx.Response:
        self._log(request)
        items = [
            {
                "id": n["id"],
                "source_system": n["payload"]["source_system"],
                "source_workspace": n["payload"]["source_workspace"],
                "source_path": n["payload"]["source_path"],
                "deleted_at": n["deleted_at"],
            }
            for n in self.notes.values()
        ]
        sources = sorted({(n["payload"]["source_workspace"]) for n in self.notes.values()})
        return httpx.Response(
            200,
            json={
                "items": items,
                "next_cursor": None,
                "sync_sources": [
                    {
                        "source_system": "obsidian",
                        "source_workspace": w,
                        "last_synced_at": "2026-10-18T14:30:00",
                        "note_count": 1,
                    }
                    for w in sources
                ],
            },
        )

    def _tombstone(self, request: httpx.Request) -> httpx.Response:
        self._log(request)
        body = json.loads(request.content)
        _TOMBSTONE_BODY.validate(body)
        done, unknown = 0, []
        for doc_id in body["source_doc_ids"]:
            note = self.notes.get(doc_id)
            if note and note["payload"]["source_workspace"] == body["source_workspace"]:
                note["deleted_at"] = "2026-10-19T00:00:00"
                done += 1
            else:
                unknown.append(doc_id)
        answer = {"tombstoned": done, "unknown": unknown}
        _TOMBSTONE_RESULT.validate(answer)
        return httpx.Response(200, json=answer)
