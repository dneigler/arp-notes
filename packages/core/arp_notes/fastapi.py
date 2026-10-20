"""build_routers(cfg): the A.2 + K§2 REST surface as two FastAPI routers. Owner: C3 (ga-mxal.10).

    private, public = build_routers(cfg, prefix="/api/v1")  # public_base_url=... behind a proxy
    app.include_router(private, prefix="/api/v1")
    app.include_router(public, prefix="/api/v1")

`private` holds every Bearer endpoint and the hygiene routes (K§6.3); each resolves the caller with
`cfg.principal.current_user_id(request)`. `public` holds the two endpoints whose credential is the
URL: `PUT /attachments/upload/{token}` and `GET /attachments/{blob_id}/content`.

The routers carry no prefix, the host mounts them. `prefix` is only what the host mounts them at.
URLs in responses (`content_url`, `thumbnail_url`, `upload_url`) are absolute so any client can use
them as they are: origin + prefix + path. The origin is the one the request came to
(`request.base_url`); a host behind a proxy that hides its public scheme or host passes
`public_base_url="https://notes.example.com"` instead.

Routes are plain `def` (FastAPI runs them in its threadpool), so a blocking psycopg2 host works.
The one exception is the upload PUT, which has to read the request stream.

Failures the core knows about are `repo.NotesError` subclasses carrying their own status and
`{"error": code}` body. A router cannot register exception handlers, so every route turns them
into a response itself. Anything else is a bug and surfaces as a 500.
"""

import argparse
import json
import logging
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Annotated, Any, BinaryIO, Literal, cast

from fastapi import APIRouter, Depends, FastAPI, Query, Request, Response, Security
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.security import HTTPBearer

from arp_notes import attachments, export, extract, hygiene, repo, review, sync
from arp_notes.config import HostConfig
from arp_notes.hygiene import routes as hygiene_routes
from arp_notes.mcp import build_capabilities
from arp_notes.models import (
    Attachment,
    AutosaveBody,
    AutosaveResult,
    Capabilities,
    ConfirmBody,
    ConfirmResult,
    EntityNotes,
    ManifestPage,
    Note,
    NoteCreate,
    NoteList,
    NotePatch,
    NoteUpsert,
    Proposal,
    TombstoneBody,
    TombstoneResult,
    UploadResult,
    UploadUrlBody,
    UploadUrlResult,
    UpsertResult,
)

log = logging.getLogger(__name__)

DEFAULT_PREFIX = "/api/v1"
# The checked-in OpenAPI document: <repo>/schemas/openapi.json (a source checkout only).
OPENAPI_PATH = Path(__file__).resolve().parents[3] / "schemas" / "openapi.json"
# Largest body the upload route spools in memory before it moves to a temp file.
SPOOL_BYTES = 1024 * 1024
# `created_via` values a client may claim on POST /notes (A.1 vocabulary).
CREATED_VIA = frozenset({"web", "mobile", "mcp", "cli", "chat", "ai"})
# Response fields holding a URL the core built relative to the mount point.
_URL_KEYS = frozenset({"content_url", "thumbnail_url", "upload_url"})

_bearer = HTTPBearer(auto_error=False, description="The host's API token. The host checks it.")


def _error(exc: repo.NotesError) -> JSONResponse:
    body = exc.body
    message = str(exc)
    if message and message != exc.code:
        body = {**body, "message": message}
    return JSONResponse(body, status_code=exc.status)


def _guarded(call: Callable[[], Any]) -> Any:
    try:
        return call()
    except repo.NotesError as exc:
        return _error(exc)


def _mounted(origin: str, prefix: str, path: str) -> str:
    """`/attachments/1/content?...` -> `https://host/api/v1/attachments/1/content?...`."""
    if not path.startswith(prefix + "/"):
        path = prefix + path
    return origin + path


class _Presenter:
    """Turns core output into response bodies: signs thumbnails, mounts URLs, adds hygiene."""

    def __init__(self, cfg: HostConfig, user_id: str, prefix: str, origin: str) -> None:
        self.cfg = cfg
        self.user_id = user_id
        self.prefix = prefix.rstrip("/")
        self.origin = origin

    def __call__(self, node: Any) -> Any:
        if isinstance(node, list):
            return [self(item) for item in node]
        if not isinstance(node, dict):
            return node
        out: dict[str, Any] = {}
        for key, value in node.items():
            if key == "thumbnail_blob_id":
                continue  # replaced by thumbnail_url below
            if key == "frontmatter":
                out[key] = value  # the user's own data: never rewritten
            elif key in _URL_KEYS and isinstance(value, str):
                out[key] = _mounted(self.origin, self.prefix, value)
            else:
                out[key] = self(value)
        blob_id = node.get("thumbnail_blob_id")
        if blob_id is not None:
            signed = attachments.content_url(self.cfg, self.user_id, blob_id)
            out["thumbnail_url"] = _mounted(self.origin, self.prefix, signed)
        return out

    def dump(self, model: Any) -> Any:
        data = self(model.model_dump(mode="json"))
        if isinstance(data, dict) and data.get("hygiene") is None:
            data.pop("hygiene", None)  # K§6.2: carried only when include_hygiene=true
        return data

    def with_hygiene(self, data: dict[str, Any], scope: str) -> dict[str, Any]:
        """K§6.2, only for `include_hygiene=true`. Best effort, like the MCP reads."""
        if not self.cfg.policy.hygiene:
            return data
        try:
            data["hygiene"] = hygiene.block(self.cfg, self.user_id, scope).model_dump(mode="json")
        except Exception:
            log.exception("hygiene block failed for scope %s", scope)
        return data


def build_routers(
    cfg: HostConfig, prefix: str = DEFAULT_PREFIX, public_base_url: str | None = None
) -> tuple[APIRouter, APIRouter]:
    """-> (private_router, public_router). Private is Bearer-authenticated by the host."""
    private = APIRouter(dependencies=[Security(_bearer)])
    public = APIRouter()

    def current_user(request: Request) -> str:
        return cfg.principal.current_user_id(request)

    def present(user_id: str, request: Request) -> _Presenter:
        origin = public_base_url or str(request.base_url)
        return _Presenter(cfg, user_id, prefix, origin.rstrip("/"))

    # Order matters: the fixed paths under /notes come before /notes/{note_id}.
    private.include_router(hygiene_routes.build_router(cfg))

    # -- capabilities and export ---------------------------------------------------------

    @private.get(
        "/notes/capabilities", response_model=Capabilities, response_model_exclude_unset=True
    )
    def get_capabilities(user_id: Annotated[str, Depends(current_user)]) -> Any:
        return build_capabilities(cfg).model_dump(mode="json")

    # -- sync ------------------------------------------------------------------------------

    @private.get(
        "/notes/sync/manifest", response_model=ManifestPage, response_model_exclude_unset=True
    )
    def get_manifest(
        user_id: Annotated[str, Depends(current_user)],
        source_system: str,
        source_workspace: str,
        limit: Annotated[int | None, Query(ge=1, le=sync.MAX_MANIFEST_PAGE)] = None,
        after: str | None = None,
    ) -> Any:
        return _guarded(
            lambda: sync.manifest(
                cfg,
                user_id,
                source_system,
                source_workspace,
                limit=limit or cfg.policy.manifest_page_size,
                after=after,
            ).model_dump(mode="json")
        )

    @private.post(
        "/notes/sync/upsert", response_model=UpsertResult, response_model_exclude_unset=True
    )
    def post_upsert(
        user_id: Annotated[str, Depends(current_user)],
        request: Request,
        body: NoteUpsert,
        include_hygiene: bool = False,
    ) -> Any:
        def run() -> Any:
            result = present(user_id, request).dump(sync.upsert(cfg, user_id, body))
            if include_hygiene:
                present(user_id, request).with_hygiene(result, f"note:{result['note_id']}")
            return result

        return _guarded(run)

    @private.post(
        "/notes/sync/tombstone", response_model=TombstoneResult, response_model_exclude_unset=True
    )
    def post_tombstone(user_id: Annotated[str, Depends(current_user)], body: TombstoneBody) -> Any:
        return _guarded(
            lambda: sync.tombstone(
                cfg, user_id, body.source_system, body.source_workspace, body.source_doc_ids
            ).model_dump(mode="json")
        )

    # -- notes: collection ---------------------------------------------------------------

    @private.get(
        "/notes/by-entity/{entity_type}/{entity_id}",
        response_model=EntityNotes,
        response_model_exclude_unset=True,
    )
    def get_by_entity(
        user_id: Annotated[str, Depends(current_user)],
        request: Request,
        entity_type: str,
        entity_id: int,
        limit: Annotated[int, Query(ge=1, le=repo.MAX_PAGE)] = 50,
        include_children: bool = False,
    ) -> Any:
        return _guarded(
            lambda: present(user_id, request).dump(
                repo.by_entity(
                    cfg,
                    user_id,
                    entity_type,
                    entity_id,
                    limit=limit,
                    include_children=include_children,
                )
            )
        )

    @private.get("/notes", response_model=NoteList, response_model_exclude_unset=True)
    def list_notes(
        user_id: Annotated[str, Depends(current_user)],
        request: Request,
        kind: str | None = None,
        origin: Literal["app", "source"] | None = None,
        source_system: str | None = None,
        q: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        limit: Annotated[int, Query(ge=1, le=repo.MAX_PAGE)] = 50,
        before: str | None = None,
        include_deleted: bool = False,
        include_hygiene: bool = False,
    ) -> Any:
        def run() -> Any:
            page = repo.list_notes(
                cfg,
                user_id,
                kind=kind,
                origin=origin,
                source_system=source_system,
                q=q,
                date_from=date_from,
                date_to=date_to,
                limit=limit,
                before=before,
                include_deleted=include_deleted,
            )
            out = present(user_id, request).dump(page)
            return present(user_id, request).with_hygiene(out, "all") if include_hygiene else out

        return _guarded(run)

    @private.post("/notes", response_model=Note, response_model_exclude_unset=True, status_code=201)
    def create_note(
        user_id: Annotated[str, Depends(current_user)], request: Request, body: NoteCreate
    ) -> Any:
        claimed = (body.model_extra or {}).get("created_via")
        created_via = claimed if claimed in CREATED_VIA else "web"
        fields = body.model_dump(include=set(NoteCreate.model_fields))
        return _guarded(
            lambda: present(user_id, request).dump(
                repo.create_note(
                    cfg, user_id, NoteCreate.model_validate(fields), created_via=created_via
                )
            )
        )

    # -- notes: one ------------------------------------------------------------------------

    @private.get("/notes/{note_id}/export", response_class=Response)
    def get_export(
        user_id: Annotated[str, Depends(current_user)],
        request: Request,
        note_id: int,
        with_enrichment: bool = False,
        enrichment_style: Literal["frontmatter", "companion"] = "frontmatter",
    ) -> Any:
        def run() -> Response:
            markdown, manifest = export.export_note(
                cfg, user_id, note_id, with_enrichment, enrichment_style
            )
            companion = with_enrichment and enrichment_style == "companion"
            headers = {
                "X-Arp-Attachments": json.dumps(
                    present(user_id, request)(manifest), separators=(",", ":"), ensure_ascii=True
                ),
                "X-Arp-Export-Part": "companion" if companion else "note",
            }
            return Response(markdown, media_type="text/markdown; charset=utf-8", headers=headers)

        return _guarded(run)

    @private.get("/notes/{note_id}", response_model=Note, response_model_exclude_unset=True)
    def get_note(
        user_id: Annotated[str, Depends(current_user)],
        request: Request,
        note_id: int,
        include_hygiene: bool = False,
    ) -> Any:
        def run() -> Any:
            out = present(user_id, request).dump(repo.get_note(cfg, user_id, note_id))
            return (
                present(user_id, request).with_hygiene(out, f"note:{note_id}")
                if include_hygiene
                else out
            )

        return _guarded(run)

    @private.patch("/notes/{note_id}", response_model=Note, response_model_exclude_unset=True)
    def patch_note(
        user_id: Annotated[str, Depends(current_user)],
        request: Request,
        note_id: int,
        body: NotePatch,
    ) -> Any:
        return _guarded(
            lambda: present(user_id, request).dump(repo.patch_note(cfg, user_id, note_id, body))
        )

    @private.patch(
        "/notes/{note_id}/autosave",
        response_model=AutosaveResult,
        response_model_exclude_unset=True,
    )
    def autosave_note(
        user_id: Annotated[str, Depends(current_user)],
        request: Request,
        note_id: int,
        body: AutosaveBody,
    ) -> Any:
        def run() -> Any:
            result = repo.autosave_note(cfg, user_id, note_id, body)
            sent = present(user_id, request).dump(result)
            # The envelope is exactly the fields that were set: {note} or the conflict triple.
            return JSONResponse(
                {key: value for key, value in sent.items() if key in result.model_fields_set}
            )

        return _guarded(run)

    @private.delete(
        "/notes/{note_id}",
        status_code=204,
        response_class=Response,
        response_model=None,
        response_model_exclude_unset=True,
    )
    def delete_note(user_id: Annotated[str, Depends(current_user)], note_id: int) -> Any:
        def run() -> Response:
            repo.delete_note(cfg, user_id, note_id)
            return Response(status_code=204)

        return _guarded(run)

    # -- enrichment ------------------------------------------------------------------------

    @private.post(
        "/notes/{note_id}/propose", response_model=Proposal, response_model_exclude_unset=True
    )
    def propose(
        user_id: Annotated[str, Depends(current_user)],
        request: Request,
        note_id: int,
        llm: bool = False,
        refresh: bool = False,
        include_hygiene: bool = False,
    ) -> Any:
        if llm and not cfg.policy.llm_enrich:
            return JSONResponse({"error": "llm_disabled"}, status_code=503)

        def run() -> Any:
            try:
                proposal = review.propose(cfg, user_id, note_id, llm=llm, refresh=refresh)
            except extract.LlmDisabled:
                return JSONResponse({"error": "llm_disabled"}, status_code=503)
            out = present(user_id, request).dump(proposal)
            return (
                present(user_id, request).with_hygiene(out, f"note:{note_id}")
                if include_hygiene
                else out
            )

        return _guarded(run)

    @private.post(
        "/notes/{note_id}/confirm", response_model=ConfirmResult, response_model_exclude_unset=True
    )
    def confirm(
        user_id: Annotated[str, Depends(current_user)], note_id: int, body: ConfirmBody
    ) -> Any:
        def run() -> Any:
            result = repo.confirm_links(cfg, user_id, note_id, body).model_dump(mode="json")
            result.update(review.apply_confirm(cfg, user_id, note_id, body))  # K§3 owns the count
            return result

        return _guarded(run)

    # -- attachments -----------------------------------------------------------------------

    @private.post(
        "/attachments/upload-url", response_model=UploadUrlResult, response_model_exclude_unset=True
    )
    def post_upload_url(
        user_id: Annotated[str, Depends(current_user)], request: Request, body: UploadUrlBody
    ) -> Any:
        def run() -> Any:
            ticket = attachments.request_upload(
                cfg, user_id, body.sha256, body.mime, body.size_bytes, body.filename
            )
            shaped = UploadUrlResult.model_validate(ticket).model_dump(
                mode="json", exclude_none=True
            )
            return JSONResponse(present(user_id, request)(shaped))

        return _guarded(run)

    @private.get(
        "/attachments/{blob_id}", response_model=Attachment, response_model_exclude_unset=True
    )
    def get_attachment(
        user_id: Annotated[str, Depends(current_user)], request: Request, blob_id: int
    ) -> Any:
        def run() -> Any:
            blob = repo.get_blob(cfg, user_id, blob_id)
            if blob is None:
                raise repo.NoteNotFound(f"attachment {blob_id} not found")
            # The Attachment shape is per embed; describe the blob by its first embed, if any.
            embed = cfg.db.run(
                "SELECT a.id, a.filename, a.ref_in_markdown FROM note_attachments a"
                " JOIN notes n ON n.id = a.note_id"
                " WHERE a.blob_id = %s AND n.user_id = %s ORDER BY a.id LIMIT 1",
                [blob_id, user_id],
            )
            first = embed[0] if embed else {}
            meta = Attachment.model_validate(
                {
                    "id": first.get("id", blob_id),
                    "blob_id": blob_id,
                    "filename": first.get("filename", blob["sha256"]),
                    "ref_in_markdown": first.get("ref_in_markdown", ""),
                    "mime": blob["mime"],
                    "size_bytes": blob["size_bytes"],
                    "sha256": blob["sha256"],
                    "width": blob["width"],
                    "height": blob["height"],
                    "content_url": attachments.content_url(cfg, user_id, blob_id),
                }
            )
            return present(user_id, request).dump(meta)

        return _guarded(run)

    @public.put(
        "/attachments/upload/{token}",
        response_model=UploadResult,
        response_model_exclude_unset=True,
        status_code=201,
    )
    async def put_upload(token: str, request: Request) -> Any:
        declared = request.headers.get("content-length", "")
        length = int(declared) if declared.isdigit() else -1
        cap = cfg.policy.max_attachment_bytes
        spool = tempfile.SpooledTemporaryFile(max_size=SPOOL_BYTES)  # noqa: SIM115
        try:
            total = 0
            async for chunk in request.stream():
                total += len(chunk)
                if total > cap:  # never hold more than a policy-sized body
                    return _error(attachments.AttachmentTooLarge(limit_bytes=cap))
                spool.write(chunk)
            spool.seek(0)
            result = await run_in_threadpool(
                _guarded,
                lambda: attachments.consume_upload(
                    cfg,
                    token,
                    cast(BinaryIO, spool),
                    request.headers.get("content-type", ""),
                    length if length >= 0 else total,
                ),
            )
        finally:
            spool.close()
        return result

    @public.get("/attachments/{blob_id}/content")
    def get_content(blob_id: int, exp: str | None = None, sig: str | None = None) -> Any:
        try:
            if exp is None or sig is None or not exp.isdigit():
                raise attachments.InvalidSignature()
            mime, chunks = attachments.open_content(cfg, blob_id, int(exp), sig)
        except repo.NotesError as exc:
            return _error(exc)
        headers = {"Cache-Control": "private, max-age=3600", "X-Content-Type-Options": "nosniff"}
        if mime == "image/svg+xml":  # user-supplied markup: show it, never run it
            headers["Content-Security-Policy"] = "default-src 'none'; sandbox"
        return StreamingResponse(chunks, media_type=mime, headers=headers)

    return private, public


def openapi_document(prefix: str = DEFAULT_PREFIX) -> dict[str, Any]:
    """The OpenAPI 3 document of the routes, as checked in at `schemas/openapi.json`.

    Built from a placeholder config: routes touch the config only when a request arrives, so the
    document does not depend on any host.
    """
    placeholder: Any = None
    cfg = HostConfig(
        db=placeholder,
        principal=placeholder,
        storage=placeholder,
        signer=placeholder,
        schemes=[],
        policy=placeholder,
    )
    app = FastAPI(
        title="arp-notes REST API",
        version="1",
        summary="Protocol 1: the notes-sync endpoints a host exposes (PROTOCOL.md A.2, K§2, K§6).",
        docs_url=None,
        redoc_url=None,
    )
    private, public = build_routers(cfg, prefix)
    app.include_router(private, prefix=prefix)
    app.include_router(public, prefix=prefix)
    return app.openapi()


def render_openapi() -> str:
    return json.dumps(openapi_document(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def main(argv: list[str] | None = None) -> int:
    """python -m arp_notes.fastapi [--check]: write schemas/openapi.json, or fail on drift."""
    parser = argparse.ArgumentParser(description="Write or check schemas/openapi.json.")
    parser.add_argument("--check", action="store_true", help="fail on drift instead of writing")
    args = parser.parse_args(argv)
    text = render_openapi()
    current = OPENAPI_PATH.read_text("utf-8") if OPENAPI_PATH.exists() else None
    if args.check:
        if current != text:
            print(f"out of date: {OPENAPI_PATH}", file=sys.stderr)
            return 1
        return 0
    if current != text:
        OPENAPI_PATH.parent.mkdir(parents=True, exist_ok=True)
        OPENAPI_PATH.write_text(text, encoding="utf-8")
    print(f"{OPENAPI_PATH} ({'written' if current != text else 'unchanged'})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
