"""Ports: what a host supplies and nothing else (ADR §9.2, K§4, K§7, K§12). Owner: C1a (ga-mxal.25).

The core is ORM-free and app-agnostic: it never imports an ORM, never assumes a users table and
never opens its own connection. Everything app-specific arrives through the objects below, bundled
in one `config.HostConfig`.

Rule (K§12): every port method that reads or writes one user's data takes `user_id` as its first
argument, because `HostConfig` is built once at startup and a port cannot be bound to a user.
Exempt, because they hold no user data: `Db`, `Principal`, `Signer`, `Policy`, `Judge`,
`LinkSchemes.dedupe_key` and `Hooks.llm_complete`. `Hygiene.detect` and the `Hooks` already
follow the rule.

Protocols describe members a host must have. Members the contract marks optional live in their own
small Protocols (`SchemeChildren`, `SchemeDedupe`, `HygieneMerge`), so a toy host can implement the
required ones only. The core finds the optional ones with `isinstance(obj, SchemeChildren)`.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, BinaryIO, Literal, Protocol, TypedDict, runtime_checkable

from arp_notes.judges import Candidate, Judgement, Mention

if TYPE_CHECKING:
    from arp_notes.models import HygieneIssue, MergePlan

__all__ = [
    "Candidate",
    "Db",
    "Hooks",
    "Hygiene",
    "HygieneMerge",
    "Judge",
    "Judgement",
    "LinkSchemes",
    "Mention",
    "Policy",
    "Principal",
    "SchemeChildren",
    "SchemeDedupe",
    "Signer",
    "Span",
    "SpanContext",
    "Storage",
]


@runtime_checkable
class Db(Protocol):
    """Raw SQL over the host's database (ADR §9.2). PT: wraps get_db(), placeholders rewritten.

    `run` returns one dict per row (empty list for statements that return none). `transaction()`
    is a context manager: commit on a clean exit, roll back on an exception.
    """

    def run(self, sql: str, params: Sequence[Any] = ()) -> list[dict[str, Any]]: ...

    def transaction(self) -> AbstractContextManager[Any]: ...


@runtime_checkable
class Principal(Protocol):
    """Who is calling (ADR §9.2). PT: require_user_id."""

    def current_user_id(self, request: Any) -> str: ...


@runtime_checkable
class Storage(Protocol):
    """Attachment bytes behind a port, keyed by (user_id, sha256) (K§12.1).

    Bytes are per user and never shared across users: two users who upload the same file each get
    a copy, which matches the `blobs` UNIQUE(user_id, sha256) key. The core verifies sha256 and
    size before it calls `put`, so adapters do not re-hash.
    """

    def put(
        self, user_id: str, sha256: str, stream: BinaryIO, *, mime: str, size_bytes: int
    ) -> str:
        """Store the bytes and return the locator kept in blobs.storage_path.

        Idempotent: when bytes already exist for (user_id, sha256) return the locator and write
        nothing. The locator is informational; the core never parses it.
        """
        ...

    def open(self, user_id: str, sha256: str) -> Iterator[bytes]:
        """Yield the bytes in chunks of at most 1 MiB.

        Raises LookupError (or a subclass) when absent, which the router turns into a 404.
        """
        ...

    def delete(self, user_id: str, sha256: str) -> None:
        """Remove the bytes. Idempotent: absent is not an error."""
        ...


@runtime_checkable
class Signer(Protocol):
    """Signs expiring content URLs (ADR §3.3). PT: SESSION_JWT_SECRET."""

    @property
    def secret(self) -> str | bytes: ...

    @property
    def ttl_s(self) -> int:
        """Seconds a signed content URL stays valid (ADR D12: 3600)."""
        ...


class SpanContext(TypedDict, total=False):
    """Context carried with a span (K§4 Mention.context)."""

    composer: str
    opus: str
    note_title: str
    note_kind: str


class Span(TypedDict):
    """A tokenised mention with carried context (K§12.2).

    Hosts receive plain dicts and import nothing. These are the K§4 `Mention` fields plus
    `kind_hint`, which uses the same vocabulary as K§2 `unresolved[].kind_hint`. Hosts must
    tolerate extra keys. `arp_notes.enrich` re-exports this type.
    """

    text: str
    quote: str
    anchor: str | None
    kind_hint: Literal["work", "composer", "movement", "technique", "person"] | None
    context: SpanContext


@runtime_checkable
class LinkSchemes(Protocol):
    """One host link scheme, for example 'pt://repertoire/:id' (ADR §9.2, K§4, K§12.2).

    A host registers one object per scheme in `HostConfig.schemes`. `entity_id` is an int on the
    wire and in `note_links`; the core converts what a port returns with `int()` and raises
    ValueError naming the scheme for anything else.
    """

    @property
    def prefix(self) -> str: ...

    @property
    def entity_types(self) -> Sequence[str]: ...

    def resolve(self, user_id: str, entity_type: str, entity_id: int) -> dict[str, Any] | None:
        """-> {title, url, preview?}, or None when missing or not visible.

        None makes the chip keep its text and show "· not found".
        """
        ...

    def search(
        self,
        user_id: str,
        q: str,
        *,
        entity_types: Sequence[str] | None = None,
        limit: int = 20,
    ) -> Sequence[Candidate | dict[str, Any]]:
        """`[[` autocomplete; best first."""
        ...

    def reconcile(
        self, user_id: str, spans: Sequence[Span]
    ) -> Sequence[Sequence[Candidate | dict[str, Any]]]:
        """The §3.4 pipeline's candidate stage: one candidate list per span.

        len(result) == len(spans), same order; [] means abstain for that span. A wrong length
        makes the core raise ValueError naming the scheme. A scheme returns [] for a span it does
        not recognise.
        """
        ...


@runtime_checkable
class SchemeChildren(Protocol):
    """Optional on a scheme: powers include_children (K§2, K§12.2)."""

    def children(self, user_id: str, entity_type: str, entity_id: int) -> list[tuple[str, int]]: ...


@runtime_checkable
class SchemeDedupe(Protocol):
    """Optional on a scheme: equal keys mean duplicate rows (K§4 step 3, K§12.2).

    Pure, no user_id. A candidate that arrives with `duplicate_group` set is a cluster the host
    already collapsed; the core does not call this on its members.
    """

    def dedupe_key(self, candidate: Candidate | dict[str, Any]) -> str | None: ...


@dataclass
class Policy:
    """Per-host capability policy; self-described by GET /notes/capabilities (ADR §9.2, K§2).

    Defaults are the ADR D12 limits: 25 MB per attachment, 200 MB per note, 2 MB body, 500
    attachments per note, 50 notes per manifest page, 15-minute upload tickets. Export is on by
    default, as the owner's doctrine requires.
    """

    attachments: bool = True
    mime_allowlist: Sequence[str] | None = None  # None = any type
    max_attachment_bytes: int = 25 * 1024 * 1024
    max_note_bytes: int = 200 * 1024 * 1024
    max_body_chars: int = 2 * 1024 * 1024
    max_attachments_per_note: int = 500
    manifest_page_size: int = 50
    upload_ticket_ttl_s: int = 15 * 60
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
    someday: bool = False  # K§5: host persists "someday" seeds
    hygiene: bool = True  # K§6: hygiene block and tools available
    propose_on_sync: Literal["off", "search", "judge"] = "search"  # K§3


@runtime_checkable
class Judge(Protocol):
    """Picks among candidates for one mention (K§4, K§12.3); optional in HostConfig.

    `name` fills GET /notes/capabilities `judge` ('jev-choice', 'jev-choice>haiku', ...).
    The Mention, Candidate and Judgement dataclasses are defined in `arp_notes.judges`.
    """

    @property
    def name(self) -> str: ...

    def judge(self, mention: Mention, candidates: list[Candidate]) -> Judgement: ...


@dataclass
class Hooks:
    """Side effects the host performs for the core (ADR §9.2, K§10). Every field is optional."""

    # (user_id, event_type, entity, summary). PT: log_activity_event. K§10 describes the
    # activity payload the adapter writes into details_json; C1b fixes the exact `entity` dict.
    on_event: Callable[[str, str, Any, str], None] | None = None
    # (user_id, link, lane) -> backlog_id. PT: practice_backlog insert.
    on_action_item: Callable[[str, Any, str], int] | None = None
    # K§5: persist a "someday" seed. Only when Policy.someday is True.
    on_someday: Callable[..., Any] | None = None
    # (prompt) -> text; the host injects the provider call. The core imports no provider SDK.
    llm_complete: Callable[[str], str] | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class Hygiene(Protocol):
    """Host-detected hygiene issues (K§6.2, K§12.3)."""

    def detect(self, user_id: str, scope: str) -> list[HygieneIssue]:
        """scope: 'all' | 'note:<id>'. The host raises duplicate_entities (detected_by='host')."""
        ...


@runtime_checkable
class HygieneMerge(Protocol):
    """Optional on a Hygiene: merge duplicate host entities (K§6.3, K§12.3)."""

    def merge(
        self,
        user_id: str,
        entity_type: str,
        keep_id: int,
        merge_ids: Sequence[int],
        dry_run: bool,
    ) -> MergePlan: ...
