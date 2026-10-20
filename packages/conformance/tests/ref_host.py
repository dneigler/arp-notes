"""The kit's own target: the C3 reference routers on a real Postgres, as an ASGI app and, through
uvicorn, as a live server (C7a, ga-mxal.14).

The smallest host an integrator would write: FakeDb + DiskStorage + one toy link scheme + a Bearer
principal behind `build_routers` mounted at /api/v1. The toy scheme's entities match the bundled
fixture (repertoire 10 with child movement 103; the masterclass note names "Op. 10 nº 3").
Registered as a plugin in conftest.py, so tests take `host_app` and `live_url` by name.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Any

import pytest
import uvicorn
from arp_notes.config import HostConfig
from arp_notes.fastapi import DEFAULT_PREFIX, build_routers
from arp_notes.mcp import TOOLS
from arp_notes.models import MergePlan
from arp_notes.ports import Hooks, Policy
from arp_notes.storage.disk import DiskStorage
from arp_notes.testing.fakedb import FakeDb
from fastapi import FastAPI, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, Response

TOKEN = "conformance-token"
USER = "conformance-user"

ENTITIES = {
    ("repertoire", 10): "Études, Op.10",
    ("movement", 103): "Op.10 nº 3",
    ("composer", 1): "Chopin",
}
CHILDREN = {("repertoire", 10): [("movement", 103)]}
RECOGNISED = {"op. 10 nº 3": ("movement", 103, 0.92), "chopin": ("composer", 1, 0.95)}


class BearerPrincipal:
    def current_user_id(self, request: Request) -> str:
        scheme, _, token = request.headers.get("authorization", "").partition(" ")
        if scheme.lower() != "bearer" or token != TOKEN:
            raise HTTPException(status_code=401, detail="missing or unknown token")
        return USER


class ToyScheme:
    prefix = "toy"
    entity_types = ("repertoire", "movement", "composer")

    def resolve(self, user_id: str, entity_type: str, entity_id: int) -> dict[str, Any] | None:
        label = ENTITIES.get((entity_type, entity_id))
        return None if label is None else {"title": label, "url": f"/{entity_type}/{entity_id}"}

    def search(
        self, user_id: str, q: str, *, entity_types: Sequence[str] | None = None, limit: int = 20
    ) -> list[dict[str, Any]]:
        return [
            {"entity_type": t, "entity_id": i, "entity_label": label, "score": 0.5}
            for (t, i), label in ENTITIES.items()
            if q.casefold() in label.casefold() and (entity_types is None or t in entity_types)
        ][:limit]

    def reconcile(self, user_id: str, spans: Sequence[Any]) -> list[list[dict[str, Any]]]:
        out: list[list[dict[str, Any]]] = []
        for span in spans:
            hit = RECOGNISED.get(str(span["text"]).casefold())
            out.append(
                []
                if hit is None
                else [
                    {
                        "entity_type": hit[0],
                        "entity_id": hit[1],
                        "entity_label": ENTITIES[(hit[0], hit[1])],
                        "score": hit[2],
                    }
                ]
            )
        return out

    def children(self, user_id: str, entity_type: str, entity_id: int) -> list[tuple[str, int]]:
        return list(CHILDREN.get((entity_type, entity_id), []))


MERGEABLE = {"repertoire": (10, {11, 12})}  # keep id, ids that fold into it (not in ENTITIES)


class ToyHygiene:
    """A host that merges: it plans repertoire 11 and 12 into 10 and refuses every other pair."""

    def detect(self, user_id: str, scope: str) -> list[Any]:
        return []

    def merge(
        self, user_id: str, entity_type: str, keep_id: int, merge_ids: Sequence[int], dry_run: bool
    ) -> MergePlan:
        keep, others = MERGEABLE.get(entity_type, (None, set()))
        if keep_id != keep or not set(merge_ids) <= others:
            raise LookupError(f"no such {entity_type} pair: {keep_id} <- {list(merge_ids)}")
        return MergePlan(
            entity_type=entity_type,
            keep=keep_id,
            merge=list(merge_ids),
            moves=[],
            conflicts=[],
            warnings=[],
        )


class FixedSigner:
    secret = "conformance-secret"
    ttl_s = 3600


def mount_mcp(app: FastAPI, cfg: HostConfig, path: str = "/mcp") -> None:
    """The smallest MCP-over-HTTP an integrator would write: JSON-RPC on one POST route, the
    tools of `arp_notes.mcp.TOOLS` called through their handlers. (Real hosts use FastMCP.)"""
    tools = {spec.name: spec for spec in TOOLS}

    @app.post(path)
    async def mcp(request: Request) -> Response:
        user_id = cfg.principal.current_user_id(request)
        message = await request.json()
        if "id" not in message:  # a notification
            return Response(status_code=202)
        method, params = message["method"], message.get("params") or {}
        result: dict[str, Any]
        if method == "initialize":
            result = {
                "protocolVersion": params.get("protocolVersion", "2025-03-26"),
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "arp-notes-reference", "version": "0"},
            }
        elif method == "tools/list":
            result = {
                "tools": [
                    {"name": t.name, "description": t.description, "inputSchema": t.input_schema}
                    for t in tools.values()
                ]
            }
        elif method == "tools/call":
            spec = tools[params["name"]]
            data = await run_in_threadpool(
                lambda: spec.handler(cfg, user_id, **(params.get("arguments") or {}))
            )
            result = {
                "content": [{"type": "text", "text": json.dumps(data)}],
                "structuredContent": data,
                "isError": False,
            }
        else:
            error = {"code": -32601, "message": f"no method {method}"}
            return JSONResponse({"jsonrpc": "2.0", "id": message["id"], "error": error})
        return JSONResponse({"jsonrpc": "2.0", "id": message["id"], "result": result})


def make_app(
    db: FakeDb,
    root: Path,
    *,
    policy: Policy | None = None,
    mcp_path: str | None = "/mcp",
    merging: bool = False,
) -> FastAPI:
    cfg = HostConfig(
        db=db,
        principal=BearerPrincipal(),
        storage=DiskStorage(root),
        signer=FixedSigner(),
        schemes=[ToyScheme()],
        policy=policy or Policy(),
        hygiene=ToyHygiene() if merging else None,
        # a merge is audited, so a host that merges must have somewhere to record it
        hooks=Hooks(on_event=lambda *event: None) if merging else None,
    )
    app = FastAPI()
    private, public = build_routers(cfg, DEFAULT_PREFIX)
    app.include_router(private, prefix=DEFAULT_PREFIX)
    app.include_router(public, prefix=DEFAULT_PREFIX)
    if mcp_path is not None:
        mount_mcp(app, cfg, mcp_path)
    return app


@pytest.fixture
def host_app(notes_db: FakeDb, tmp_path: Path) -> FastAPI:
    return make_app(notes_db, tmp_path / "blobs")


@pytest.fixture
def live_url(host_app: FastAPI) -> Iterator[str]:
    """The host served by uvicorn on a free local port: what --base-url mode talks to."""
    server = uvicorn.Server(
        uvicorn.Config(host_app, host="127.0.0.1", port=0, log_level="warning", lifespan="on")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    while not server.started:
        if not thread.is_alive():
            raise RuntimeError("uvicorn exited before it started")
        thread.join(0.02)
    port = server.servers[0].sockets[0].getsockname()[1]
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(10)
