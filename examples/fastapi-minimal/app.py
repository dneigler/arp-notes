"""fastapi-minimal: the smallest arp-notes host, in one file (ADR §9.8).

Everything an integrator writes is here: a `Db` over psycopg, a Bearer-token `Principal`, one toy
link scheme, the `HostConfig` that bundles them, the router mount and an MCP endpoint. Copy it,
swap each class for your app's own, and the conformance kit (`test_app.py`) tells you when you are
done. It is also the kit's CI target.

Run it (Postgres needed):

    createdb notes_example
    export DATABASE_URL=postgresql:///notes_example EXAMPLE_TOKEN=dev-token
    uv run python app.py migrate                      # applies ./migrations
    uv run uvicorn app:create_app --factory --port 8000
    uv run arp-notes-conformance --base-url http://127.0.0.1:8000 --token dev-token
"""

from __future__ import annotations

import json
import os
import sys
import threading
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import psycopg
from arp_notes.config import HostConfig
from arp_notes.fastapi import DEFAULT_PREFIX, build_routers
from arp_notes.mcp import TOOLS
from arp_notes.ports import Hooks, Policy
from arp_notes.storage.disk import DiskStorage
from fastapi import FastAPI, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, Response
from psycopg.rows import dict_row

HERE = Path(__file__).resolve().parent


# -- Db: raw SQL over the app's own database --------------------------------------------------
class PsycopgDb:
    """`ports.Db` over psycopg 3. One short-lived connection per call; inside `transaction()` the
    calls of that thread share one connection. A real app hands over its own pool or session."""

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn
        self._local = threading.local()

    def _open(self) -> psycopg.Connection[Any]:
        conn: psycopg.Connection[Any] = psycopg.connect(self._dsn, autocommit=True)
        conn.row_factory = dict_row
        return conn

    @contextmanager
    def _connection(self) -> Iterator[psycopg.Connection[Any]]:
        active = getattr(self._local, "conn", None)
        if active is not None:
            yield active
            return
        with self._open() as conn:
            yield conn

    def run(self, sql: str, params: Sequence[Any] = ()) -> list[dict[str, Any]]:
        values = tuple(params)
        query: Any = sql  # built at runtime by design; the core writes %s placeholders
        with self._connection() as conn:
            cur = conn.execute(query, values or None)
            return list(cur.fetchall()) if cur.description else []

    @contextmanager
    def transaction(self) -> Iterator[PsycopgDb]:
        if getattr(self._local, "conn", None) is not None:  # nested: a savepoint
            with self._local.conn.transaction():
                yield self
            return
        with self._open() as conn:
            self._local.conn = conn
            try:
                with conn.transaction():
                    yield self
            finally:
                self._local.conn = None


# -- Principal: who is calling ----------------------------------------------------------------
class BearerPrincipal:
    """`Authorization: Bearer <token>` -> user id, else 401. Your app already has this."""

    def __init__(self, tokens: dict[str, str]) -> None:
        self._tokens = tokens

    def current_user_id(self, request: Request) -> str:
        scheme, _, token = request.headers.get("authorization", "").partition(" ")
        user_id = self._tokens.get(token) if scheme.lower() == "bearer" else None
        if user_id is None:
            raise HTTPException(status_code=401, detail="missing or unknown token")
        return user_id


class FixedSigner:
    """Signs the expiring content URLs. Use your session secret; here it is a constant."""

    def __init__(self, secret: str) -> None:
        self.secret = secret
        self.ttl_s = 3600


# -- LinkSchemes: what a note can link to ------------------------------------------------------
ENTITIES: dict[tuple[str, int], str] = {
    ("repertoire", 10): "Études, Op.10",
    ("movement", 103): "Op.10 nº 3",
    ("composer", 1): "Chopin",
}
CHILDREN: dict[tuple[str, int], list[tuple[str, int]]] = {("repertoire", 10): [("movement", 103)]}
RECOGNISED: dict[str, tuple[str, int, float]] = {  # mention text (casefolded) -> entity, score
    "op. 10 nº 3": ("movement", 103, 0.92),
    "chopin": ("composer", 1, 0.95),
}


class ToyScheme:
    """One link scheme over a dict. `user_id` comes first on every method; a real scheme filters
    by it. `reconcile` returns one candidate list per span, in order; `[]` abstains."""

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
        return list(CHILDREN.get((entity_type, entity_id), []))  # optional: include_children


# -- HostConfig: the one object ---------------------------------------------------------------
def build_host_config(
    db: Any, blob_dir: str | os.PathLike[str], tokens: dict[str, str], secret: str = "dev-secret"
) -> HostConfig:
    return HostConfig(
        db=db,
        principal=BearerPrincipal(tokens),
        storage=DiskStorage(blob_dir),
        signer=FixedSigner(secret),
        schemes=[ToyScheme()],
        policy=Policy(),  # defaults: attachments on (25 MB each), export on, search-only proposals
        hooks=Hooks(
            on_event=lambda user_id, event_type, entity, summary: None
        ),  # your activity log
    )


# -- MCP: a hand-maintained registry ----------------------------------------------------------
def mount_mcp(app: FastAPI, cfg: HostConfig, path: str = "/mcp") -> None:
    """MCP over HTTP in its smallest form: JSON-RPC on one POST route serving `arp_notes.mcp.TOOLS`.

    An app with a FastMCP server calls `arp_notes.mcp.register_fastmcp(server, cfg)` instead.
    """
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
                "serverInfo": {"name": "fastapi-minimal", "version": "0"},
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


# -- The app ----------------------------------------------------------------------------------
def make_app(cfg: HostConfig, prefix: str = DEFAULT_PREFIX) -> FastAPI:
    app = FastAPI(title="arp-notes fastapi-minimal")
    private, public = build_routers(cfg, prefix)  # public = the signed content URLs
    app.include_router(private, prefix=prefix)
    app.include_router(public, prefix=prefix)
    mount_mcp(app, cfg)
    return app


def create_app() -> FastAPI:
    """`uvicorn app:create_app --factory`. DATABASE_URL, EXAMPLE_TOKEN and BLOB_DIR from the env."""
    db = PsycopgDb(os.environ["DATABASE_URL"])
    token = os.environ["EXAMPLE_TOKEN"]
    blob_dir = os.environ.get("BLOB_DIR", str(HERE / "data" / "blobs"))
    return make_app(build_host_config(db, blob_dir, {token: "example-user"}))


# -- Migrations are copied, not imported ------------------------------------------------------
def migrate(db: PsycopgDb, directory: Path = HERE / "migrations") -> list[str]:
    """Apply every copied SQL file in order. Each is idempotent, so running twice is safe."""
    applied = []
    for path in sorted(directory.glob("*.sql")):
        db.run(path.read_text(encoding="utf-8"))
        applied.append(path.name)
    return applied


if __name__ == "__main__":
    if sys.argv[1:] == ["migrate"]:
        print("\n".join(migrate(PsycopgDb(os.environ["DATABASE_URL"]))))
    else:
        sys.exit(__doc__)
