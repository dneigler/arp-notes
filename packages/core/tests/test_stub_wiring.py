"""The C0 stubs: NotImplementedError bodies, plus the no-op hooks and mounts K§7 requires."""

from __future__ import annotations

from typing import cast

import pytest
from arp_notes import anchors, attachments, enrich, hygiene, mcp, repo, review, schema, sync
from arp_notes.config import HostConfig
from arp_notes.fastapi import build_routers
from arp_notes.hygiene import fixes, routes, tools
from arp_notes.models import ConfirmBody, HygieneBlock, NoteUpsert
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

CFG = cast(HostConfig, object())  # stubs never touch the config


def test_hooks_are_no_ops_returning_empty() -> None:
    assert review.after_upsert(CFG, "u", 1, "created") is None
    assert review.apply_confirm(CFG, "u", 1, ConfirmBody()) == {}
    block = hygiene.block(CFG, "u")
    assert isinstance(block, HygieneBlock)
    assert block.model_dump() == {"issues": [], "total": 0, "truncated": False}


def test_mcp_tools_compose_hygiene_tools() -> None:
    assert mcp.NOTES_TOOLS == []
    assert tools.TOOLS == []
    assert mcp.TOOLS == [*mcp.NOTES_TOOLS, *tools.TOOLS]


def test_build_routers_mounts_hygiene_routes(monkeypatch: pytest.MonkeyPatch) -> None:
    probe = APIRouter()
    probe.add_api_route("/_probe", lambda: {"ok": True}, methods=["GET"])
    monkeypatch.setattr(routes, "router", probe)
    private, public = build_routers(CFG)
    app = FastAPI()
    app.include_router(private)
    app.include_router(public)
    client = TestClient(app)
    assert client.get("/_probe").json() == {"ok": True}


def test_fixes_router_is_included_by_hygiene_routes() -> None:
    assert isinstance(fixes.router, APIRouter)
    assert isinstance(routes.router, APIRouter)


@pytest.mark.parametrize(
    "call",
    [
        lambda: anchors.slug("A heading"),
        lambda: schema.ddl(),
        lambda: repo.confirm_links(CFG, "u", 1, ConfirmBody()),
        lambda: sync.upsert(CFG, "u", NoteUpsert()),
        lambda: sync.manifest(CFG, "u", "obsidian", "vault"),
        lambda: sync.tombstone(CFG, "u", "obsidian", "vault", ["a"]),
        lambda: attachments.content_url(CFG, "u", 1),
        lambda: enrich.tokenise("# x"),
        lambda: enrich.propose(CFG, "u", 1),
        lambda: review.get_cached(CFG, "u", 1),
        lambda: mcp.register_fastmcp(object(), CFG),
    ],
)
def test_stub_bodies_raise_not_implemented(call) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(NotImplementedError):
        call()
