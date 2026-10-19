"""Fakes and fixtures for the repo/sync tests (C1b, ga-mxal.8).

Registered as a plugin in conftest.py, so tests take `notes_cfg`, `fake_scheme` and `fake_hooks`
by name and import only the helpers. `signed_urls` stands in for `attachments.content_url`, a C2
stub until that lands; opt in with::

    pytestmark = pytest.mark.usefixtures("signed_urls")
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterator, Sequence
from typing import Any, BinaryIO

import pytest
from arp_notes import attachments
from arp_notes.config import HostConfig
from arp_notes.models import NoteUpsert
from arp_notes.ports import Hooks, Policy
from arp_notes.testing.fakedb import FakeDb

USER = "u1"
OTHER = "u2"


def sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


class FakePrincipal:
    def current_user_id(self, request: Any) -> str:
        return USER


class FakeStorage:
    def put(
        self, user_id: str, sha256: str, stream: BinaryIO, *, mime: str, size_bytes: int
    ) -> str:
        return sha256

    def open(self, user_id: str, sha256: str) -> Iterator[bytes]:
        raise LookupError(sha256)

    def delete(self, user_id: str, sha256: str) -> None:
        return None


class FakeSigner:
    secret = "test-secret"
    ttl_s = 3600


class FakeScheme:
    """A toy host link scheme: a dict of entities and, optionally, parent -> children."""

    prefix = "t"
    entity_types = ("repertoire", "movement", "composer", "technique")

    def __init__(
        self,
        entities: dict[tuple[str, int], str] | None = None,
        kids: dict[tuple[str, int], list[tuple[str, int]]] | None = None,
    ) -> None:
        self.entities = entities or {}
        self.kids = kids or {}

    def resolve(self, user_id: str, entity_type: str, entity_id: int) -> dict[str, Any] | None:
        title = self.entities.get((entity_type, entity_id))
        return None if title is None else {"title": title, "url": f"/{entity_type}/{entity_id}"}

    def search(
        self, user_id: str, q: str, *, entity_types: Sequence[str] | None = None, limit: int = 20
    ) -> list[dict[str, Any]]:
        return []

    def reconcile(self, user_id: str, spans: Sequence[Any]) -> list[list[dict[str, Any]]]:
        return [[] for _ in spans]

    def children(self, user_id: str, entity_type: str, entity_id: int) -> list[tuple[str, int]]:
        return list(self.kids.get((entity_type, entity_id), []))


class FakeHooks(Hooks):
    """Records every call. `on_action_item` hands out backlog ids 100, 101, ..."""

    def __init__(self) -> None:
        super().__init__()
        self.events: list[tuple[str, str, Any, str]] = []
        self.actions: list[tuple[str, Any, str]] = []
        self.someday: list[tuple[str, int, dict[str, Any]]] = []
        self._next_backlog = 100
        self.on_event = self._on_event
        self.on_action_item = self._on_action_item

    def _on_event(self, user_id: str, event_type: str, entity: Any, summary: str) -> None:
        self.events.append((user_id, event_type, entity, summary))

    def _on_action_item(self, user_id: str, link: Any, lane: str) -> int:
        self.actions.append((user_id, link, lane))
        self._next_backlog += 1
        return self._next_backlog - 1

    def enable_someday(self) -> None:
        def record(user_id: str, note_id: int, item: dict[str, Any]) -> None:
            self.someday.append((user_id, note_id, item))

        self.on_someday = record

    def names(self) -> list[str]:
        return [event[1] for event in self.events]


def make_cfg(
    db: FakeDb,
    *,
    scheme: FakeScheme | None = None,
    hooks: Hooks | None = None,
    policy: Policy | None = None,
) -> HostConfig:
    return HostConfig(
        db=db,
        principal=FakePrincipal(),
        storage=FakeStorage(),
        signer=FakeSigner(),
        schemes=[scheme or FakeScheme()],
        policy=policy or Policy(),
        hooks=hooks,
    )


@pytest.fixture
def fake_scheme() -> FakeScheme:
    return FakeScheme(
        {
            ("repertoire", 35): "Études, Op.10",
            ("movement", 12): "Op.10 nº 12",
            ("movement", 3): "Op.10 nº 3",
            ("composer", 1): "Chopin",
            ("technique", 7): "Legato",
        }
    )


@pytest.fixture
def fake_hooks() -> FakeHooks:
    return FakeHooks()


@pytest.fixture
def notes_cfg(notes_db: FakeDb, fake_scheme: FakeScheme, fake_hooks: FakeHooks) -> HostConfig:
    return make_cfg(notes_db, scheme=fake_scheme, hooks=fake_hooks)


@pytest.fixture
def signed_urls(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake(cfg: HostConfig, user_id: str, blob_id: int) -> str:
        return f"/attachments/{blob_id}/content?sig=test"

    monkeypatch.setattr(attachments, "content_url", fake)


def add_blob(
    db: FakeDb, user_id: str = USER, *, text: str = "img", mime: str = "image/webp"
) -> tuple[int, str]:
    """Register a blob row for `text`. -> (blob id, sha256)."""
    digest = sha(text)
    row = db.run(
        "INSERT INTO blobs (user_id, sha256, mime, size_bytes, storage_path)"
        " VALUES (%s, %s, %s, %s, %s) ON CONFLICT (user_id, sha256) DO UPDATE SET mime = %s"
        " RETURNING id",
        [user_id, digest, mime, len(text), digest, mime],
    )
    return row[0]["id"], digest


def upsert_body(
    doc_id: str = "d1",
    body_md: str = "# Intro\n\ntext\n",
    *,
    path: str | None = None,
    attachments: Sequence[dict[str, Any]] = (),
    **over: Any,
) -> NoteUpsert:
    data: dict[str, Any] = {
        "source_system": "obsidian",
        "source_workspace": "Vault",
        "source_doc_id": doc_id,
        "source_path": path or f"{doc_id}.md",
        "title": f"Note {doc_id}",
        "body_md": body_md,
        "content_hash": sha(body_md),
        "attachments": list(attachments),
    }
    data.update(over)
    return NoteUpsert.model_validate(data)


def attachment_ref(digest: str, ref: str, filename: str | None = None) -> dict[str, Any]:
    return {
        "sha256": digest,
        "filename": filename or ref.strip("![]"),
        "mime": "image/webp",
        "size_bytes": 3,
        "ref_in_markdown": ref,
    }


def add_note(
    db: FakeDb,
    user_id: str = USER,
    *,
    title: str = "A note",
    origin: str = "app",
    **cols: Any,
) -> int:
    """Insert a notes row directly. -> note id."""
    values: dict[str, Any] = {"user_id": user_id, "title": title, "origin": origin, **cols}
    names = ", ".join(values)
    marks = ", ".join(["%s"] * len(values))
    return db.run(
        f"INSERT INTO notes ({names}) VALUES ({marks}) RETURNING id", list(values.values())
    )[0]["id"]


def add_link(
    db: FakeDb,
    note_id: int,
    entity_type: str,
    entity_id: int,
    *,
    user_id: str = USER,
    anchor: str | None = None,
    status: str = "confirmed",
    **cols: Any,
) -> int:
    values: dict[str, Any] = {
        "note_id": note_id,
        "user_id": user_id,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "anchor": anchor,
        "status": status,
        **cols,
    }
    names = ", ".join(values)
    marks = ", ".join(["%s"] * len(values))
    return db.run(
        f"INSERT INTO note_links ({names}) VALUES ({marks}) RETURNING id", list(values.values())
    )[0]["id"]
