"""The reference host for the REST tests (C3, ga-mxal.10): the smallest app that mounts the routers.

FakeDb (a real Postgres) + DiskStorage + one toy link scheme + a Bearer-token principal, behind
`build_routers` mounted at /api/v1, exactly as an integrator would (INTEGRATING.md, C9).

Registered as a plugin in conftest.py, so tests take `ref` (the `Ref` below) by name and import the
helpers. Synthetic data only.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import jsonschema
import pytest
from arp_notes import schemas
from arp_notes.config import HostConfig
from arp_notes.fastapi import DEFAULT_PREFIX, build_routers
from arp_notes.ports import Hooks, Policy
from arp_notes.schemas import generate
from arp_notes.storage.disk import DiskStorage
from arp_notes.testing.fakedb import FakeDb
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient
from repo_support import FakeHooks, FakeSigner

SCHEMAS_DIR = Path(schemas.__file__).parent
API = DEFAULT_PREFIX
ORIGIN = "http://testserver"  # what TestClient calls itself; URLs in responses start with it

TOKENS = {"tok-u1": "u1", "tok-u2": "u2"}
ALICE = {"Authorization": "Bearer tok-u1"}
BOB = {"Authorization": "Bearer tok-u2"}

# Toy entities: (entity_type, id) -> label. Movement 103 is a child of repertoire 10.
ENTITIES: dict[tuple[str, int], str] = {
    ("repertoire", 10): "Études, Op.10",
    ("movement", 103): "Op.10 nº 3",
    ("movement", 112): "Op.10 nº 12",
    ("composer", 1): "Chopin",
    ("technique", 7): "Legato",
}
CHILDREN: dict[tuple[str, int], list[tuple[str, int]]] = {
    ("repertoire", 10): [("movement", 103), ("movement", 112)],
    ("composer", 1): [("repertoire", 10)],
}
# span text (casefolded) -> candidate. What the toy host's reconcile recognises.
RECOGNISED: dict[str, tuple[str, int, float]] = {
    "op. 10 nº 3": ("movement", 103, 0.92),
    "chopin": ("composer", 1, 0.95),
}


class BearerPrincipal:
    """Authorization: Bearer <token> -> user id, else 401 (a real host uses its own scheme)."""

    def current_user_id(self, request: Request) -> str:
        header = request.headers.get("authorization", "")
        scheme, _, token = header.partition(" ")
        user = TOKENS.get(token) if scheme.lower() == "bearer" else None
        if user is None:
            raise HTTPException(status_code=401, detail="missing or unknown token")
        return user


class ToyScheme:
    """A link scheme over a dict: enough for resolve, search, reconcile and children."""

    prefix = "toy"
    entity_types = ("repertoire", "movement", "composer", "technique")

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


def make_cfg(db: FakeDb, root: Path, *, policy: Policy | None = None, hooks: Hooks | None = None):
    return HostConfig(
        db=db,
        principal=BearerPrincipal(),
        storage=DiskStorage(root),
        signer=FakeSigner(),
        schemes=[ToyScheme()],
        policy=policy or Policy(),
        hooks=hooks,
    )


def make_app(cfg: HostConfig, prefix: str = API, public_base_url: str | None = None) -> FastAPI:
    app = FastAPI()
    private, public = build_routers(cfg, prefix, public_base_url)
    app.include_router(private, prefix=prefix)
    app.include_router(public, prefix=prefix)
    return app


@dataclass
class Ref:
    """The reference app under test: its config, a client and the fakes behind it."""

    cfg: HostConfig
    db: FakeDb
    hooks: FakeHooks
    root: Path
    client: TestClient

    def with_policy(self, **changes: Any) -> Ref:
        """A client on the same database and storage with `Policy` fields changed."""
        policy = Policy(**{**vars(self.cfg.policy), **changes})
        cfg = make_cfg(self.db, self.root, policy=policy, hooks=self.hooks)
        return Ref(cfg, self.db, self.hooks, self.root, TestClient(make_app(cfg)))

    # Short forms: every call is Alice unless it passes `headers`.
    def get(self, path: str, **kw: Any) -> Any:
        return self.client.get(API + path, **{"headers": ALICE, **kw})

    def post(self, path: str, **kw: Any) -> Any:
        return self.client.post(API + path, **{"headers": ALICE, **kw})

    def patch(self, path: str, **kw: Any) -> Any:
        return self.client.patch(API + path, **{"headers": ALICE, **kw})

    def delete(self, path: str, **kw: Any) -> Any:
        return self.client.delete(API + path, **{"headers": ALICE, **kw})

    def put(self, path: str, **kw: Any) -> Any:
        return self.client.put(API + path, **kw)


@pytest.fixture
def ref(notes_db: FakeDb, tmp_path: Path) -> Ref:
    hooks = FakeHooks()
    cfg = make_cfg(notes_db, tmp_path / "blobs", hooks=hooks)
    return Ref(cfg, notes_db, hooks, tmp_path / "blobs", TestClient(make_app(cfg)))


def validate(shape: str, body: Any) -> None:
    """The body validates against schemas/<shape>.json (the contract's JSON Schema)."""
    path = SCHEMAS_DIR / f"{generate.file_stem(shape)}.json"
    jsonschema.Draft202012Validator(json.loads(path.read_text("utf-8"))).validate(body)


def ok(response: Any, shape: str | None = None, status: int = 200) -> Any:
    """Assert the status, validate the JSON body against `shape`, return the body."""
    assert response.status_code == status, response.text
    if status == 204:
        return None
    body = response.json()
    if shape:
        validate(shape, body)
    return body


def fails(response: Any, status: int, error: str | None = None) -> Any:
    """Assert an error status and, when given, its `{"error": code}`."""
    assert response.status_code == status, response.text
    body = response.json()
    if error:
        validate("ErrorBody", body)
        assert body["error"] == error, body
    return body
