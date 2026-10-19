"""Pydantic v2 models for every A.2 + K§2 + K§6 shape; schemas/*.json are generated from them.

Owner: C1a (ga-mxal.25). Sources: ADR Appendix A.2 (shapes and endpoint bodies), contract K§2
(REST deltas), K§6.1/K§6.3 (hygiene), K§12.4 (names ratified from C0).

Conventions
- `X | None = None` is the contract's `?`: optional and nullable. Clients and servers tolerate
  unknown fields (K§2), so every model allows extras.
- Response models list their required fields without defaults, so a schema check on a response
  catches a missing one. Request models default their lists to empty so a client can omit them.
- Timestamps are ISO-8601 strings on the wire. A datetime handed to a model (a DB row, say) is
  converted with `.isoformat()`, so a host can pass rows straight in.
- `note_date` is a 'YYYY-MM-DD' string (the house TEXT-date convention), never a date type.
- Entity types stay open strings: they are the host's vocabulary (PT: 'repertoire', 'movement',
  'section', 'composer', 'technique', 'instructor').
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field

SHA256_PATTERN = r"^[0-9a-f]{64}$"


def _to_iso(value: Any) -> Any:
    if isinstance(value, datetime | date):
        return value.isoformat()
    return value


Timestamp = Annotated[
    str,
    BeforeValidator(_to_iso),
    Field(description="ISO-8601 timestamp, e.g. 2026-10-18T14:30:00"),
]
Sha256 = Annotated[str, Field(pattern=SHA256_PATTERN, description="64 lowercase hex characters")]
Confidence = Annotated[float, Field(ge=0.0, le=1.0)]

KindHint = Literal["work", "composer", "movement", "technique", "person"]
LinkStatus = Literal["confirmed", "rejected", "orphaned"]
Lane = Literal["practice", "lesson"]
Severity = Literal["info", "warn", "action"]
HygieneKind = Literal[
    "duplicate_entities",
    "tombstoned_note",
    "pending_review",
    "orphaned_links",
    "unreferenced_blobs",
    "unresolved_mentions",
]


class _Model(BaseModel):
    # Clients and servers tolerate unknown fields (K§2).
    model_config = ConfigDict(extra="allow")


# ---------------------------------------------------------------------------------------------
# Notes (A.2, K§2)
# ---------------------------------------------------------------------------------------------


class Attachment(_Model):
    id: int
    blob_id: int
    filename: str
    ref_in_markdown: str
    mime: str
    size_bytes: int
    sha256: Sha256
    width: int | None = None
    height: int | None = None
    content_url: str = Field(description="Signed URL; expires within 1 hour")


class EntityRef(_Model):
    """A (entity_type, entity_id) pair, used by `NoteLink.via`."""

    entity_type: str
    entity_id: int


class NoteLink(_Model):
    id: int
    entity_type: str
    entity_id: int
    entity_label: str
    entity_slug: str | None = None
    anchor: str | None = Field(
        default=None, description="Heading slug or ^block-id; null = whole note"
    )
    quote: str | None = None
    comment: str | None = None
    action_item: str | None = None
    action_completed: int
    backlog_id: int | None = None
    status: LinkStatus
    proposed_by: str | None = None
    confidence: Confidence | None = None
    sort_order: int
    via: EntityRef | None = Field(
        default=None,
        description="K§2: set on by-entity results that matched through a child entity",
    )


class TopLink(_Model):
    """K§2 NoteSummary.top_links item."""

    entity_type: str
    entity_id: int
    entity_label: str


class Note(_Model):
    id: int
    user_id: str
    kind: str
    title: str
    body_md: str
    frontmatter: dict[str, Any]
    person: str | None = None
    note_date: str | None = None
    place: str | None = None
    origin: Literal["app", "source"]
    source_system: str | None = None
    source_workspace: str | None = None
    source_doc_id: str | None = None
    source_path: str | None = None
    source_url: str | None = None
    source_modified_at: str | None = None
    content_hash: Sha256 | None = None
    last_synced_at: Timestamp | None = None
    deleted_at: Timestamp | None = None
    created_via: str
    version: int
    created_at: Timestamp
    updated_at: Timestamp
    attachments: list[Attachment]
    links: list[NoteLink]
    review_pending: int
    proposed_at: Timestamp | None = None
    hygiene: HygieneBlock | None = Field(
        default=None, description="K§6.2: present only when include_hygiene=true"
    )


class NoteSummary(_Model):
    id: int
    kind: str
    title: str
    person: str | None = None
    note_date: str | None = None
    origin: Literal["app", "source"]
    source_system: str | None = None
    last_synced_at: Timestamp | None = None
    deleted_at: Timestamp | None = None
    link_count: int
    attachment_count: int
    updated_at: Timestamp
    # K§2 additions
    source_workspace: str | None = None
    source_path: str | None = None
    thumbnail_url: str | None = Field(
        default=None, description="Signed content_url of the first image attachment, valid 1 h"
    )
    top_links: list[TopLink] = Field(description="At most 4 confirmed links")
    action_count: int
    review_pending: int
    duration_min: int | None = None


class SyncSource(_Model):
    """K§2: one row of the 'Last sync' line in GET /notes."""

    source_system: str
    source_workspace: str
    last_synced_at: Timestamp | None = None
    note_count: int


class NoteList(_Model):
    """GET /notes response."""

    items: list[NoteSummary]
    next_cursor: str | None = None
    sync_sources: list[SyncSource]
    hygiene: HygieneBlock | None = Field(
        default=None, description="K§6.2: present only when include_hygiene=true"
    )


class EntityNote(_Model):
    note: NoteSummary
    links: list[NoteLink]


class EntityNotes(_Model):
    """GET /notes/by-entity/{entity_type}/{entity_id} response."""

    items: list[EntityNote]


class NoteCreate(_Model):
    """POST /notes body (origin='app')."""

    kind: str | None = None
    title: str
    body_md: str | None = None
    person: str | None = None
    note_date: str | None = None
    place: str | None = None


class NotePatch(_Model):
    """PATCH /notes/{id} body. kind/person/note_date/place are editable on both origins."""

    kind: str | None = None
    title: str | None = None
    body_md: str | None = None
    person: str | None = None
    note_date: str | None = None
    place: str | None = None


class AutosaveBody(_Model):
    body_md: str
    version: int


class AutosaveResult(_Model):
    """PATCH /notes/{id}/autosave: {note} on success, or the house conflict envelope."""

    note: Note | None = None
    conflict: bool | None = None
    server_version: int | None = None
    server_data: Note | None = None


# ---------------------------------------------------------------------------------------------
# Sync (A.2, K§12.4)
# ---------------------------------------------------------------------------------------------


class ManifestRow(_Model):
    source_doc_id: str
    source_path: str
    content_hash: Sha256
    attachments: list[Sha256]
    last_synced_at: Timestamp
    deleted_at: Timestamp | None = None


class ManifestPage(_Model):
    """GET /notes/sync/manifest response (K§12.4). `protocol` is ADR §9.4."""

    protocol: int = 1
    items: list[ManifestRow]
    next_after: str | None = None


class UpsertAttachment(_Model):
    sha256: Sha256
    filename: str
    mime: str
    size_bytes: int
    ref_in_markdown: str


class NoteUpsert(_Model):
    source_system: str
    source_workspace: str
    source_doc_id: str
    source_path: str
    title: str
    body_md: str
    frontmatter: dict[str, Any] | None = None
    source_modified_at: str | None = None
    source_url: str | None = None
    content_hash: Sha256
    kind: str | None = None
    person: str | None = None
    note_date: str | None = None
    place: str | None = None
    attachments: list[UpsertAttachment] = Field(default_factory=list)


class UpsertResult(_Model):
    note_id: int
    outcome: Literal["created", "updated", "unchanged"]
    missing_attachments: list[Sha256]
    links_orphaned: int
    hygiene: HygieneBlock | None = Field(
        default=None, description="K§6.2: present only when include_hygiene=true"
    )


class TombstoneBody(_Model):
    source_system: str
    source_workspace: str
    source_doc_ids: list[str]


class TombstoneResult(_Model):
    tombstoned: int
    unknown: list[str]


# ---------------------------------------------------------------------------------------------
# Proposals and confirmation (A.2, K§2, K§3)
# ---------------------------------------------------------------------------------------------


class ProposalCandidate(_Model):
    """One pickable candidate on an ambiguous ProposedLink or an unresolved mention."""

    entity_type: str
    entity_id: int
    entity_label: str
    confidence: Confidence
    duplicate_group: str | None = Field(
        default=None,
        description="K§2: equal values mark the same work or composer by the K§4 dedupe key",
    )


class ProposedLink(_Model):
    entity_type: str
    entity_id: int
    entity_label: str
    anchor: str | None = None
    quote: str
    confidence: Confidence
    proposed_by: str
    reason: str
    candidates: list[ProposalCandidate] | None = Field(
        default=None, description="Present means ambiguous: the user must pick one"
    )
    mention_count: int | None = Field(
        default=None, description="K§2: composer rows, 'Mentioned 14 times'"
    )


class ProposedAction(_Model):
    text: str
    anchor: str | None = None
    entity_type: str | None = None
    entity_id: int | None = None
    lane: Lane
    proposed_by: str


class UnresolvedMention(_Model):
    mention: str
    anchor: str | None = None
    quote: str
    candidates: list[ProposalCandidate]
    kind_hint: KindHint | None = None
    composer_label: str | None = None


class Proposal(_Model):
    note_id: int
    links: list[ProposedLink]
    action_items: list[ProposedAction]
    takeaways: list[str]
    unresolved: list[UnresolvedMention]
    generated_by: list[Literal["resolver", "llm"]]
    cached: bool = Field(description="K§2: true when served from notes.proposal")
    proposed_at: Timestamp | None = Field(description="K§2: when the proposal was computed")
    hygiene: HygieneBlock | None = Field(
        default=None, description="K§6.2: present only when include_hygiene=true"
    )


class ConfirmLink(_Model):
    entity_type: str
    entity_id: int
    anchor: str | None = None
    quote: str | None = None
    comment: str | None = None
    proposed_by: str | None = None
    confidence: Confidence | None = None


class RejectedLink(_Model):
    entity_type: str
    entity_id: int
    anchor: str | None = None


class ConfirmAction(_Model):
    text: str
    anchor: str | None = None
    entity_type: str | None = None
    entity_id: int | None = None
    lane: Lane
    link_index: int | None = Field(default=None, description="Attach to links[i]")


class ConfirmTakeaway(_Model):
    anchor: str | None = None
    comment: str


class DeferredMention(_Model):
    """K§2: an ambiguous item the user left for later."""

    mention: str
    anchor: str | None = None


class SomedayMention(_Model):
    """K§2/K§5: an unresolved mention the user switched on as a 'someday' idea."""

    mention: str
    kind_hint: KindHint | None = None
    composer_label: str | None = None
    anchor: str | None = None
    quote: str | None = None


class ConfirmBody(_Model):
    links: list[ConfirmLink] = Field(default_factory=list)
    rejected: list[RejectedLink] = Field(default_factory=list)
    action_items: list[ConfirmAction] = Field(default_factory=list)
    takeaways: list[ConfirmTakeaway] | None = None
    deferred: list[DeferredMention] | None = None
    someday: list[SomedayMention] | None = Field(
        default=None,
        description='K§5: 422 {"error":"someday_unsupported"} when capabilities.someday=false',
    )


class ConfirmResult(_Model):
    links_created: int
    links_rejected: int
    backlog_created: list[int]
    takeaways_created: int
    someday_created: int
    review_pending: int


# ---------------------------------------------------------------------------------------------
# Attachments (A.2, A.4)
# ---------------------------------------------------------------------------------------------


class UploadUrlBody(_Model):
    sha256: Sha256
    mime: str
    size_bytes: int
    filename: str


class UploadUrlResult(_Model):
    """POST /attachments/upload-url response: status 'exists' or 'upload'."""

    status: Literal["exists", "upload"]
    blob_id: int | None = Field(default=None, description="status=exists")
    upload_url: str | None = Field(default=None, description="status=upload")
    method: Literal["PUT"] | None = Field(default=None, description="status=upload")
    expires_at: Timestamp | None = Field(default=None, description="status=upload")


class UploadResult(_Model):
    """PUT /attachments/upload/{token} response (201)."""

    blob_id: int
    sha256: Sha256


class ErrorBody(_Model):
    """The `{"error": ...}` envelope used by 409/422/503 responses in A.2 and K§2."""

    error: str = Field(
        description="blob_missing | hash_mismatch | read_only_import | llm_disabled | "
        "someday_unsupported | plan_changed | ..."
    )
    missing: list[Sha256] | None = Field(default=None, description="error=blob_missing")


# ---------------------------------------------------------------------------------------------
# Capabilities (A.2, K§2, K§12.4)
# ---------------------------------------------------------------------------------------------


class CapabilityLimits(_Model):
    max_attachment_bytes: int
    max_note_bytes: int
    max_body_chars: int
    max_attachments_per_note: int
    manifest_page_size: int
    upload_ticket_ttl_s: int


class CapabilityScheme(_Model):
    prefix: str
    entity_types: list[str]


class Capabilities(_Model):
    """GET /notes/capabilities: built from Policy plus schemes and the judge name (K§12.4)."""

    protocol: Literal[1]
    attachments: bool
    mime_allowlist: list[str] | None
    limits: CapabilityLimits
    kinds: list[str]
    source_systems: list[str]
    export: bool
    llm_enrich: bool
    schemes: list[CapabilityScheme]
    someday: bool
    hygiene: bool
    propose_on_sync: Literal["off", "search", "judge"]
    judge: str | None


# ---------------------------------------------------------------------------------------------
# Hygiene (K§6)
# ---------------------------------------------------------------------------------------------


class HygieneSubject(_Model):
    entity_type: str
    entity_id: int
    label: str


class HygieneFix(_Model):
    label: str
    tool: str
    arguments: dict[str, Any]
    dry_run_first: bool
    reversible: bool


class HygieneIssue(_Model):
    key: str = Field(
        description="Stable: '<kind>:<entity_type>:<sorted ids joined by ,>' or '<kind>:note:<id>'"
    )
    kind: HygieneKind
    severity: Severity
    title: str
    explanation: str = Field(description="Plain language for the client LLM to relay")
    subjects: list[HygieneSubject]
    fixes: list[HygieneFix]
    detected_by: Literal["core", "host"]


class HygieneBlock(_Model):
    issues: list[HygieneIssue] = Field(max_length=10)
    total: int
    truncated: bool


class MergeMove(_Model):
    table: str
    column: str
    rows: int


class MergeConflict(_Model):
    table: str
    detail: str


class MergePlan(_Model):
    entity_type: str
    keep: int
    merge: list[int]
    moves: list[MergeMove]
    conflicts: list[MergeConflict]
    reversible: Literal[False] = False
    warnings: list[str]


class DismissBody(_Model):
    issue_key: str
    reason: str | None = None


class DismissResult(_Model):
    dismissed: bool


class ResolveTombstoneBody(_Model):
    action: Literal["keep", "delete"]


class ResolveTombstoneResult(_Model):
    note_id: int
    action: Literal["keep", "delete"]


class ApplyFixBody(_Model):
    issue_key: str
    fix_index: int
    confirm_token: str | None = None


class ApplyFixDryRun(_Model):
    dry_run: Literal[True]
    plan: dict[str, Any]
    confirm_token: str
    expires_at: Timestamp


class ApplyFixApplied(_Model):
    applied: Literal[True]
    result: dict[str, Any]


class MergeEntitiesBody(_Model):
    entity_type: str
    keep_id: int
    merge_ids: list[int]
    dry_run: bool = True
    confirm_token: str | None = None


class MergeEntitiesDryRun(_Model):
    plan: MergePlan
    confirm_token: str
    expires_at: Timestamp


class MergeEntitiesApplied(_Model):
    applied: Literal[True]
    audit_event_id: int


# Forward references: Note, NoteList, Proposal and UpsertResult name HygieneBlock before it is
# defined (the annotations are strings under `from __future__ import annotations`).
for _model in (Note, NoteList, Proposal, UpsertResult, AutosaveResult):
    _model.model_rebuild()
