"""Ports: what a host supplies and nothing else (ADR §9.2, K§4, K§7). Owner: C1a (ga-mxal.25).

C0 stub: the Protocols carry the signatures written in §9.2 and K§4; C1a finalises them.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, BinaryIO, Protocol

if TYPE_CHECKING:
    from arp_notes.judges import Candidate, Judgement, Mention
    from arp_notes.models import HygieneIssue, MergePlan


class Db(Protocol):
    """PT: wraps get_db(); '?' placeholders already rewritten."""

    def run(self, sql: str, params: Sequence[Any] = ()) -> list[dict[str, Any]]: ...

    def transaction(self) -> AbstractContextManager[Any]: ...


class Principal(Protocol):
    def current_user_id(self, request: Any) -> str: ...


class Storage(Protocol):
    """Attachment bytes behind a port; the core never assumes a backend."""

    def put(self, sha256: str, stream: BinaryIO) -> str:
        """Store the bytes; return the backend locator kept in blobs.storage_path."""
        ...

    def open(self, sha256: str) -> Iterator[bytes]: ...

    def delete(self, sha256: str) -> None: ...


class Signer(Protocol):
    secret: str | bytes
    ttl: int  # seconds a signed content URL stays valid


class LinkSchemes(Protocol):
    """One host link scheme, e.g. 'pt://repertoire/:id' (K§4)."""

    prefix: str
    entity_types: Sequence[str]

    def resolve(self, entity_type: str, entity_id: int) -> dict[str, Any]:
        """-> {title, url, preview}"""
        ...

    def search(self, q: str) -> list[Candidate]: ...

    def reconcile(self, spans: Sequence[Any]) -> list[Candidate]: ...

    # Optional (K§4).
    def children(self, entity_type: str, entity_id: int) -> list[tuple[str, int]]: ...

    def dedupe_key(self, candidate: Candidate) -> str | None: ...


@dataclass
class Policy:
    """Per-host capability policy; self-described by GET /notes/capabilities (K§2)."""

    attachments: bool = True
    mime_allowlist: Sequence[str] | None = None
    max_attachment_bytes: int = 25 * 1024 * 1024
    max_note_bytes: int = 200 * 1024 * 1024
    max_body_chars: int = 2 * 1024 * 1024
    kinds: Sequence[str] = (
        "masterclass",
        "workshop",
        "lecture",
        "reading",
        "video",
        "reflection",
        "meeting",
        "note",
    )
    source_systems: Sequence[str] = ("obsidian", "notion", "apple_notes", "llm")
    export: bool = True
    llm_enrich: bool = False
    someday: bool = False
    hygiene: bool = False
    propose_on_sync: str = "off"  # 'off' | 'search' | 'judge'


class Judge(Protocol):
    def judge(self, mention: Mention, candidates: list[Candidate]) -> Judgement: ...


@dataclass
class Hooks:
    # (user_id, event_type, entity, summary)
    on_event: Callable[[str, str, Any, str], None] | None = None
    # (user_id, link, lane) -> backlog_id
    on_action_item: Callable[[str, Any, str], int] | None = None
    on_someday: Callable[..., Any] | None = None
    llm_complete: Callable[[str], str] | None = None
    extra: dict[str, Any] = field(default_factory=dict)


class Hygiene(Protocol):
    def detect(self, user_id: str, scope: str) -> list[HygieneIssue]: ...

    # Optional.
    def merge(
        self, entity_type: str, keep_id: int, merge_ids: Sequence[int], dry_run: bool
    ) -> MergePlan: ...
