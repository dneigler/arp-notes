"""Hygiene REST routes (K§6.3), mounted by arp_notes.fastapi.build_routers. Owner: H1a (ga-mxal.30).

Routes need the request's HostConfig, so they are built per config: `build_router(cfg)` returns a
router with GET /notes/hygiene, POST /hygiene/dismiss and POST /notes/{note_id}/resolve-tombstone,
plus H1b's fixes router. The module-level `router` is the config-free part (H1b's fixes router
only, until it too takes a config). `build_routers` must mount `build_router(cfg)`.

Mount it before any `/notes/{note_id}` route, so `/notes/hygiene` is not read as a note id.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from arp_notes import hygiene
from arp_notes.config import HostConfig
from arp_notes.hygiene import fixes
from arp_notes.models import (
    DismissBody,
    DismissResult,
    HygieneBlock,
    ResolveTombstoneBody,
    ResolveTombstoneResult,
)
from arp_notes.repo import NoteNotFound, NotesError

router = APIRouter()
router.include_router(fixes.router)


def _error(exc: NotesError) -> JSONResponse:
    body = exc.body
    message = str(exc)
    if message and message != exc.code:
        body = {**body, "message": message}
    return JSONResponse(body, status_code=exc.status)


def build_router(cfg: HostConfig) -> APIRouter:
    """The hygiene endpoints for one host config (the caller is `cfg.principal`)."""
    built = APIRouter()

    def guarded(request: Request, call: Callable[[str], Any]) -> Any:
        user_id = cfg.principal.current_user_id(request)
        try:
            return call(user_id)
        except NotesError as exc:
            return _error(exc)

    @built.get("/notes/hygiene", response_model=HygieneBlock)
    def get_hygiene(request: Request, scope: str = "all") -> Any:
        def run(user_id: str) -> HygieneBlock:
            result = hygiene.block(cfg, user_id, scope)
            if scope.startswith("note:"):
                found = cfg.db.run(
                    "SELECT 1 FROM notes WHERE id = %s AND user_id = %s",
                    [int(scope[5:]), user_id],
                )
                if not found:
                    raise NoteNotFound(f"note {scope[5:]} not found")
            return result

        return guarded(request, run)

    @built.post("/hygiene/dismiss", response_model=DismissResult)
    def post_dismiss(request: Request, body: DismissBody) -> Any:
        return guarded(
            request, lambda user_id: hygiene.dismiss(cfg, user_id, body.issue_key, body.reason)
        )

    @built.post("/notes/{note_id}/resolve-tombstone", response_model=ResolveTombstoneResult)
    def post_resolve_tombstone(request: Request, note_id: int, body: ResolveTombstoneBody) -> Any:
        return guarded(
            request, lambda user_id: hygiene.resolve_tombstone(cfg, user_id, note_id, body.action)
        )

    built.include_router(router)
    return built
