"""The C0 stubs: NotImplementedError bodies, plus the no-op hooks and mounts K§7 requires."""

from __future__ import annotations

from typing import cast

import pytest
from arp_notes import attachments, mcp
from arp_notes.config import HostConfig
from arp_notes.fastapi import build_routers
from arp_notes.hygiene import fixes, routes, tools
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

CFG = cast(HostConfig, object())  # stubs never touch the config


def test_mcp_tools_compose_hygiene_tools() -> None:
    assert len(mcp.NOTES_TOOLS) == 13  # C4 (ga-mxal.11)
    assert [spec.name for spec in tools.TOOLS] == [
        "dismiss_issue",
        "resolve_tombstone",  # H1a
        "apply_fix",
        "merge_entities",  # H1b
    ]
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
        lambda: attachments.content_url(CFG, "u", 1),
    ],
)
def test_stub_bodies_raise_not_implemented(call) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(NotImplementedError):
        call()
