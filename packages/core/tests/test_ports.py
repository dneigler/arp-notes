"""Protocol conformance with toy hosts, and HostConfig/Policy defaults (ADR §9.2, K§12)."""

from __future__ import annotations

import dataclasses
import hashlib
import io
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from typing import Any, BinaryIO

import pytest
from arp_notes import enrich, ports
from arp_notes.config import HostConfig
from arp_notes.judges import Candidate, Judgement, Mention
from arp_notes.ports import (
    Db,
    Hooks,
    Hygiene,
    HygieneMerge,
    Judge,
    LinkSchemes,
    Policy,
    Principal,
    SchemeChildren,
    SchemeDedupe,
    Signer,
    Span,
    Storage,
)

CHUNK = 1024 * 1024


class ToyStorage:
    """Per-user, in-memory bytes keyed by (user_id, sha256), as K§12.1 requires."""

    def __init__(self) -> None:
        self._blobs: dict[tuple[str, str], bytes] = {}

    def put(
        self, user_id: str, sha256: str, stream: BinaryIO, *, mime: str, size_bytes: int
    ) -> str:
        self._blobs.setdefault((user_id, sha256), stream.read())  # idempotent
        return f"{sha256[:2]}/{sha256}"

    def open(self, user_id: str, sha256: str) -> Iterator[bytes]:
        try:
            data = self._blobs[(user_id, sha256)]
        except KeyError:
            raise LookupError(f"no blob {sha256} for user") from None
        return (data[i : i + CHUNK] for i in range(0, len(data), CHUNK))

    def delete(self, user_id: str, sha256: str) -> None:
        self._blobs.pop((user_id, sha256), None)


class ToyScheme:
    """The minimum a host implements: no children, no dedupe_key."""

    prefix = "toy"
    entity_types = ("piece",)

    def __init__(self) -> None:
        self.rows = {("u1", 1): "Sonata", ("u2", 1): "Etude"}

    def resolve(self, user_id: str, entity_type: str, entity_id: int) -> dict[str, Any] | None:
        title = self.rows.get((user_id, entity_id))
        return None if title is None else {"title": title, "url": f"/piece/{entity_id}"}

    def search(
        self,
        user_id: str,
        q: str,
        *,
        entity_types: Sequence[str] | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        return [
            {"entity_type": "piece", "entity_id": i, "entity_label": t, "score": 0.9}
            for (u, i), t in self.rows.items()
            if u == user_id and q.lower() in t.lower()
        ][:limit]

    def reconcile(self, user_id: str, spans: Sequence[Span]) -> list[list[dict[str, Any]]]:
        return [self.search(user_id, s["text"]) for s in spans]


class FullScheme(ToyScheme):
    def children(self, user_id: str, entity_type: str, entity_id: int) -> list[tuple[str, int]]:
        return [("piece", 2)]

    def dedupe_key(self, candidate: Candidate | dict[str, Any]) -> str | None:
        return None


class ToyDb:
    def run(self, sql: str, params: Sequence[Any] = ()) -> list[dict[str, Any]]:
        return []

    @contextmanager
    def transaction(self) -> Iterator[None]:
        yield


class ToyPrincipal:
    def current_user_id(self, request: Any) -> str:
        return "u1"


class ToySigner:
    secret = "s3cret"
    ttl_s = 3600


class ToyJudge:
    name = "toy"

    def judge(self, mention: Mention, candidates: list[Candidate]) -> Judgement:
        return Judgement(choice=None, confidence=0.0, judge=self.name, stage="work")


class ToyHygiene:
    def detect(self, user_id: str, scope: str) -> list[Any]:
        return []


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def put(storage: Storage, user_id: str, data: bytes) -> str:
    return storage.put(user_id, sha(data), io.BytesIO(data), mime="image/png", size_bytes=len(data))


def test_toys_satisfy_the_protocols() -> None:
    # Static: pyright checks these assignments. Runtime: isinstance checks member presence.
    storage: Storage = ToyStorage()
    scheme: LinkSchemes = ToyScheme()
    db: Db = ToyDb()
    principal: Principal = ToyPrincipal()
    signer: Signer = ToySigner()
    judge: Judge = ToyJudge()
    hygiene: Hygiene = ToyHygiene()
    for obj, proto in [
        (storage, Storage),
        (scheme, LinkSchemes),
        (db, Db),
        (principal, Principal),
        (signer, Signer),
        (judge, Judge),
        (hygiene, Hygiene),
    ]:
        assert isinstance(obj, proto)


def test_storage_isolates_two_users_with_the_same_sha256() -> None:
    storage: Storage = ToyStorage()
    # The same sha256 for two users but different bytes: the key is (user_id, sha256).
    digest = sha(b"shared-key")
    storage.put("u1", digest, io.BytesIO(b"bytes for one"), mime="image/png", size_bytes=13)
    storage.put("u2", digest, io.BytesIO(b"bytes for two"), mime="image/png", size_bytes=13)
    assert b"".join(storage.open("u1", digest)) == b"bytes for one"
    assert b"".join(storage.open("u2", digest)) == b"bytes for two"

    storage.delete("u1", digest)
    with pytest.raises(LookupError):
        storage.open("u1", digest)
    assert b"".join(storage.open("u2", digest)) == b"bytes for two"  # u2 untouched


def test_storage_put_is_idempotent_and_delete_of_absent_is_not_an_error() -> None:
    storage = ToyStorage()
    first = put(storage, "u1", b"abc")
    assert put(storage, "u1", b"abc") == first
    storage.delete("u1", sha(b"never stored"))
    storage.delete("u1", sha(b"abc"))
    storage.delete("u1", sha(b"abc"))


def test_storage_open_yields_chunks_of_at_most_one_mib() -> None:
    storage = ToyStorage()
    data = b"x" * (CHUNK * 2 + 5)
    put(storage, "u1", data)
    chunks = list(storage.open("u1", sha(data)))
    assert [len(c) for c in chunks] == [CHUNK, CHUNK, 5]


def test_scheme_resolution_is_per_user() -> None:
    scheme = ToyScheme()
    assert scheme.resolve("u1", "piece", 1) == {"title": "Sonata", "url": "/piece/1"}
    assert scheme.resolve("u2", "piece", 1) == {"title": "Etude", "url": "/piece/1"}
    assert scheme.resolve("u3", "piece", 1) is None  # not visible -> chip keeps its text


def test_reconcile_returns_one_candidate_list_per_span() -> None:
    spans: list[Span] = [
        {"text": "sonata", "quote": "q", "anchor": None, "kind_hint": None, "context": {}},
        {"text": "nothing", "quote": "q", "anchor": "intro", "kind_hint": "work", "context": {}},
    ]
    result = ToyScheme().reconcile("u1", spans)
    assert len(result) == len(spans)
    assert [c["entity_label"] for c in result[0]] == ["Sonata"]
    assert result[1] == []  # abstain


def test_optional_scheme_members_are_separate_protocols() -> None:
    assert not isinstance(ToyScheme(), SchemeChildren)
    assert not isinstance(ToyScheme(), SchemeDedupe)
    assert isinstance(FullScheme(), SchemeChildren)
    assert isinstance(FullScheme(), SchemeDedupe)
    assert isinstance(FullScheme(), LinkSchemes)


def test_hygiene_merge_is_optional_and_takes_user_id() -> None:
    class Merging(ToyHygiene):
        def merge(
            self,
            user_id: str,
            entity_type: str,
            keep_id: int,
            merge_ids: Sequence[int],
            dry_run: bool,
        ) -> Any:
            return {"keep": keep_id}

    assert not isinstance(ToyHygiene(), HygieneMerge)
    assert isinstance(Merging(), HygieneMerge)


def test_span_is_defined_in_ports_and_reexported_by_enrich() -> None:
    assert enrich.Span is ports.Span
    assert set(Span.__annotations__) == {"text", "quote", "anchor", "kind_hint", "context"}


def test_candidate_carries_the_k12_fields() -> None:
    fields = {f.name for f in dataclasses.fields(Candidate)}
    assert {"composer_label", "duplicates", "duplicate_group", "children"} <= fields


def test_judge_protocol_requires_a_name() -> None:
    class Nameless:
        def judge(self, mention: Mention, candidates: list[Candidate]) -> Judgement: ...

    assert not isinstance(Nameless(), Judge)
    assert isinstance(ToyJudge(), Judge)


def make_config(**overrides: Any) -> HostConfig:
    base: dict[str, Any] = {
        "db": ToyDb(),
        "principal": ToyPrincipal(),
        "storage": ToyStorage(),
        "signer": ToySigner(),
        "schemes": [ToyScheme()],
        "policy": Policy(),
    }
    return HostConfig(**{**base, **overrides})


def test_host_config_is_frozen_with_optional_extras() -> None:
    cfg = make_config()
    assert (cfg.judge, cfg.hooks, cfg.hygiene) == (None, None, None)
    with pytest.raises(dataclasses.FrozenInstanceError):
        cfg.policy = Policy(export=False)  # type: ignore[misc]
    assert [f.name for f in dataclasses.fields(HostConfig)] == [
        "db", "principal", "storage", "signer", "schemes", "policy", "judge", "hooks", "hygiene",
    ]  # fmt: skip


def test_host_config_accepts_every_port() -> None:
    cfg = make_config(judge=ToyJudge(), hooks=Hooks(), hygiene=ToyHygiene())
    assert cfg.judge is not None and cfg.judge.name == "toy"
    assert cfg.hooks == Hooks()


def test_policy_defaults_are_the_d12_limits() -> None:
    p = Policy()
    assert p.attachments is True
    assert p.mime_allowlist is None
    assert p.max_attachment_bytes == 25 * 1024 * 1024
    assert p.max_note_bytes == 200 * 1024 * 1024
    assert p.max_body_chars == 2 * 1024 * 1024
    assert p.max_attachments_per_note == 500
    assert p.manifest_page_size == 50
    assert p.upload_ticket_ttl_s == 15 * 60
    assert p.export is True
    assert p.propose_on_sync == "search"
    assert p.someday is False
    assert p.hygiene is True
    assert p.llm_enrich is False
    assert "masterclass" in p.kinds
    assert set(p.source_systems) == {"obsidian", "notion", "apple_notes", "llm"}


def test_hooks_default_to_nothing() -> None:
    h = Hooks()
    assert (h.on_event, h.on_action_item, h.on_someday, h.llm_complete) == (None, None, None, None)
