"""MCP tool specs (A.3 + K§6.3) and FastMCP registration. Owner: C4 (ga-mxal.11).

TOOLS = [*NOTES_TOOLS, *hygiene.tools.TOOLS]. C4 fills NOTES_TOOLS (13 specs); H1a/H1b fill the
hygiene specs (4), for 17 in total.

Handlers are `handler(cfg, user_id, **args) -> dict` (ADR §9.2). They validate `args` against the
tool's `input_schema`, call the core module that serves the matching REST endpoint, and return a
JSON-ready dict, never a bare list. A failure the REST layer reports as an HTTP error comes back
as the same body (`{"error": code, ...}`), so a client LLM sees one error shape on both surfaces.

Hosts whose MCP layer calls REST instead of the core (PT's mcp_host.py via api_call) use
`REST_BINDINGS` / `rest_request` to generate their wrappers from the same specs.
"""

from __future__ import annotations

import asyncio
import functools
import importlib
import inspect
import logging
import string
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Annotated, Any, Literal, NamedTuple

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from arp_notes import attachments, enrich, hygiene, repo, review, sync
from arp_notes.config import HostConfig
from arp_notes.hygiene import tools as hygiene_tools
from arp_notes.models import (
    Capabilities,
    CapabilityLimits,
    CapabilityScheme,
    ConfirmBody,
    NoteCreate,
    NotePatch,
    NoteUpsert,
    TombstoneBody,
    UploadUrlBody,
    UploadUrlResult,
)

log = logging.getLogger(__name__)

# get_note cuts the body here (A.3) so one huge note cannot swamp a client's context window.
NOTE_BODY_LIMIT = 20_000
# Only value of create_note.source_system (A.3): notes an LLM wrote through MCP.
LLM_SOURCE = "llm"


@dataclass
class ToolSpec:
    name: str
    description: str
    input_schema: dict[str, Any]
    handler: Callable[..., Any]  # handler(config, user_id, **args)
    writes: bool = False  # the R/W column of A.3


# ---------------------------------------------------------------------------------------------
# Argument models: one per tool. They validate the call and generate input_schema, so the schema
# a client sees and the validation a handler does cannot drift apart.
# ---------------------------------------------------------------------------------------------


class _Args(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _NoArgs(_Args):
    pass


class _NoteId(_Args):
    note_id: int = Field(description="The note's id, as returned by list_notes.")


class _ListNotes(_Args):
    kind: str | None = Field(
        None, description="Filter by kind, e.g. masterclass, lecture, meeting, note."
    )
    origin: Literal["app", "source"] | None = Field(
        None, description="'source' = imported from Obsidian/Notion/etc.; 'app' = written here."
    )
    source_system: str | None = Field(
        None, description="Filter by source: obsidian, notion, apple_notes or llm."
    )
    q: str | None = Field(None, description="Text search over title, body and person.")
    date_from: str | None = Field(None, description="Earliest note_date, YYYY-MM-DD.")
    date_to: str | None = Field(None, description="Latest note_date, YYYY-MM-DD.")
    limit: int | None = Field(None, ge=1, le=100, description="Page size, 1-100.")
    before: str | None = Field(
        None, description="The next_cursor of the previous page, to fetch the next one."
    )


class _GetNotesForEntity(_Args):
    entity_type: str = Field(description="Host entity type, e.g. repertoire, composer.")
    entity_id: int = Field(description="The entity's id.")
    limit: int | None = Field(None, ge=1, le=100, description="Maximum notes to return.")
    include_children: bool | None = Field(
        None,
        description="Also return notes linked to the entity's children "
        "(a piece's movements, a composer's pieces).",
    )


class _CreateNote(_Args):
    title: str = Field(description="Note title.")
    body_md: str | None = Field(None, description="Markdown body. Text only, no attachments.")
    kind: str | None = Field(None, description="Kind, e.g. reflection or note (the default).")
    person: str | None = Field(None, description="Presenter or author, free text.")
    note_date: str | None = Field(None, description="YYYY-MM-DD.")
    place: str | None = Field(None, description="Where it happened.")
    source_system: Literal["llm"] | None = Field(
        None, description="Pass 'llm' together with source_doc_id to make the call retry-safe."
    )
    source_doc_id: str | None = Field(
        None,
        description="A client-chosen unique id (a uuid). Creating again with the same id "
        "returns the existing note instead of a duplicate.",
    )


class _UpdateNote(_Args):
    note_id: int = Field(description="The note's id.")
    title: str | None = Field(None, description="New title. Refused for imported notes.")
    body_md: str | None = Field(None, description="New Markdown body. Refused for imported notes.")
    kind: str | None = Field(None, description="New kind.")
    person: str | None = Field(None, description='New person; "" clears it.')
    note_date: str | None = Field(None, description='New date, YYYY-MM-DD; "" clears it.')
    place: str | None = Field(None, description='New place; "" clears it.')


class _Manifest(_Args):
    source_system: str = Field(description="obsidian, notion, apple_notes or llm.")
    source_workspace: str = Field(description="Vault folder name, Notion workspace id, etc.")
    limit: int | None = Field(None, ge=1, le=500, description="Page size, at most 500.")
    after: str | None = Field(
        None, description="The next_after of the previous page, to fetch the next one."
    )


class _Proposal(_Args):
    note_id: int = Field(description="The note's id.")
    llm: bool | None = Field(
        None, description="Also ask the LLM pass for takeaways and action items (if enabled)."
    )
    refresh: bool | None = Field(
        None, description="Recompute instead of returning the cached proposal."
    )


_CLEARABLE = ("person", "note_date", "place")


class _Confirm(ConfirmBody):
    note_id: int = Field(description="The note's id.")


# NoteUpsert and ConfirmBody already are the A.2 request shapes; reuse them as the tool inputs.
_Upsert = NoteUpsert


def _drop_titles(node: Any) -> Any:
    """Remove pydantic's auto-generated 'title' keys but keep properties named 'title'."""
    if isinstance(node, dict):
        out: dict[str, Any] = {}
        for key, value in node.items():
            if key == "title" and isinstance(value, str):
                continue
            if key in ("properties", "$defs"):
                out[key] = {name: _drop_titles(sub) for name, sub in value.items()}
            else:
                out[key] = _drop_titles(value)
        return out
    if isinstance(node, list):
        return [_drop_titles(item) for item in node]
    return node


def _is_null(branch: Any) -> bool:
    return isinstance(branch, dict) and branch.get("type") == "null"


def _schema(model: type[BaseModel]) -> dict[str, Any]:
    """The model's JSON Schema, tidied for an LLM: optional means 'omit', not 'send null'."""
    schema = _drop_titles(model.model_json_schema())
    for prop in schema.get("properties", {}).values():
        branches = prop.get("anyOf")
        if branches:
            rest = [b for b in branches if not _is_null(b)]
            if len(rest) == 1 and len(rest) < len(branches):
                prop.pop("anyOf")
                prop.update(rest[0])
        if prop.get("default", ...) is None:
            prop.pop("default")
    return {"$schema": "https://json-schema.org/draft/2020-12/schema", **schema}


# ---------------------------------------------------------------------------------------------
# Handler plumbing
# ---------------------------------------------------------------------------------------------


def _error(exc: repo.NotesError) -> dict[str, Any]:
    body = exc.body
    message = str(exc)
    if message and message != exc.code:
        body = {**body, "message": message}
    return body


def _handler(
    model: type[BaseModel],
) -> Callable[[Callable[..., dict[str, Any]]], Callable[..., Any]]:
    """Turn `fn(cfg, user_id, args)` into `handler(cfg, user_id, **raw_args) -> dict`."""

    def decorate(fn: Callable[..., dict[str, Any]]) -> Callable[..., dict[str, Any]]:
        @functools.wraps(fn)
        def handler(cfg: HostConfig, user_id: str, **raw: Any) -> dict[str, Any]:
            try:
                args = model.model_validate(raw)
            except ValidationError as exc:
                detail = [
                    {"field": ".".join(str(p) for p in e["loc"]), "problem": e["msg"]}
                    for e in exc.errors()
                ]
                return {"error": "invalid_arguments", "detail": detail}
            try:
                return fn(cfg, user_id, args)
            except repo.NotesError as exc:
                return _error(exc)

        return handler

    return decorate


def _json(model: BaseModel) -> dict[str, Any]:
    return model.model_dump(mode="json")


def _with_hygiene(
    cfg: HostConfig, user_id: str, data: dict[str, Any], scope: str
) -> dict[str, Any]:
    """K§6.2: MCP reads always carry the hygiene block, so the client LLM can act on it.

    Best effort: a broken detector must not make a read tool fail. The key is left out when the
    host turned hygiene off (capabilities.hygiene = false).
    """
    data.pop("hygiene", None)
    if not cfg.policy.hygiene:
        return data
    try:
        data["hygiene"] = _json(hygiene.block(cfg, user_id, scope))
    except Exception:
        log.exception("hygiene block failed for scope %s", scope)
    return data


def truncate_body(note: dict[str, Any], limit: int = NOTE_BODY_LIMIT) -> dict[str, Any]:
    """A.3 get_note: cut `body_md` at `limit` characters and say so with `truncated: true`.

    Public so a host whose MCP layer calls REST (and so skips the handler) applies the same rule.
    """
    body = note.get("body_md") or ""
    if len(body) > limit:
        return {**note, "body_md": body[:limit], "truncated": True, "body_md_chars": len(body)}
    return {**note, "truncated": False}


def _only(args: BaseModel, *, exclude: tuple[str, ...] = ()) -> dict[str, Any]:
    """The arguments the caller actually sent (not None), minus `exclude`."""
    return {
        name: getattr(args, name)
        for name in args.model_fields_set
        if name not in exclude and getattr(args, name) is not None
    }


# ---------------------------------------------------------------------------------------------
# The 13 notes tools (A.3)
# ---------------------------------------------------------------------------------------------


def build_capabilities(cfg: HostConfig) -> Capabilities:
    """GET /notes/capabilities, built from Policy plus schemes and the judge name (K§12.4)."""
    policy = cfg.policy
    return Capabilities(
        protocol=1,
        attachments=policy.attachments,
        mime_allowlist=list(policy.mime_allowlist) if policy.mime_allowlist is not None else None,
        limits=CapabilityLimits(
            max_attachment_bytes=policy.max_attachment_bytes,
            max_note_bytes=policy.max_note_bytes,
            max_body_chars=policy.max_body_chars,
            max_attachments_per_note=policy.max_attachments_per_note,
            manifest_page_size=policy.manifest_page_size,
            upload_ticket_ttl_s=policy.upload_ticket_ttl_s,
        ),
        kinds=list(policy.kinds),
        source_systems=list(policy.source_systems),
        export=policy.export,
        llm_enrich=policy.llm_enrich,
        schemes=[
            CapabilityScheme(prefix=s.prefix, entity_types=list(s.entity_types))
            for s in cfg.schemes
        ],
        someday=policy.someday,
        hygiene=policy.hygiene,
        propose_on_sync=policy.propose_on_sync,
        judge=cfg.judge.name if cfg.judge is not None else None,
    )


@_handler(_NoArgs)
def _notes_capabilities(cfg: HostConfig, user_id: str, args: _NoArgs) -> dict[str, Any]:
    return _json(build_capabilities(cfg))


@_handler(_ListNotes)
def _list_notes(cfg: HostConfig, user_id: str, args: _ListNotes) -> dict[str, Any]:
    page = repo.list_notes(cfg, user_id, **_only(args))
    return _with_hygiene(cfg, user_id, _json(page), "all")


@_handler(_NoteId)
def _get_note(cfg: HostConfig, user_id: str, args: _NoteId) -> dict[str, Any]:
    note = repo.get_note(cfg, user_id, args.note_id)
    data = truncate_body(_json(note))
    return _with_hygiene(cfg, user_id, data, f"note:{args.note_id}")


@_handler(_GetNotesForEntity)
def _get_notes_for_entity(
    cfg: HostConfig, user_id: str, args: _GetNotesForEntity
) -> dict[str, Any]:
    found = repo.by_entity(
        cfg,
        user_id,
        args.entity_type,
        args.entity_id,
        **_only(args, exclude=("entity_type", "entity_id")),
    )
    return _json(found)


def _existing_llm_note(cfg: HostConfig, user_id: str, doc_id: str) -> int | None:
    rows = cfg.db.run(
        "SELECT id FROM notes WHERE user_id = %s AND source_system = %s AND source_doc_id = %s"
        " AND source_workspace IS NULL ORDER BY id LIMIT 1",
        [user_id, LLM_SOURCE, doc_id],
    )
    return rows[0]["id"] if rows else None


@_handler(_CreateNote)
def _create_note(cfg: HostConfig, user_id: str, args: _CreateNote) -> dict[str, Any]:
    doc_id = args.source_doc_id
    if doc_id is not None:
        found = _existing_llm_note(cfg, user_id, doc_id)
        if found is not None:
            note = _json(repo.get_note(cfg, user_id, found))
            return {**note, "already_existed": True}
    body = NoteCreate.model_validate(_only(args, exclude=("source_system", "source_doc_id")))
    note = repo.create_note(cfg, user_id, body, created_via="mcp")
    if args.source_system or doc_id is not None:
        cfg.db.run(
            "UPDATE notes SET source_system = %s, source_doc_id = %s"
            " WHERE id = %s AND user_id = %s",
            [LLM_SOURCE, doc_id, note.id, user_id],
        )
        note = repo.get_note(cfg, user_id, note.id)
    return _json(note)


@_handler(_UpdateNote)
def _update_note(cfg: HostConfig, user_id: str, args: _UpdateNote) -> dict[str, Any]:
    # "" (or an explicit null, for a caller that can send one) clears person/note_date/place.
    sent = {n: getattr(args, n) for n in args.model_fields_set if n != "note_id"}
    for name in _CLEARABLE:
        if sent.get(name) == "":
            sent[name] = None
    return _json(repo.patch_note(cfg, user_id, args.note_id, NotePatch.model_validate(sent)))


@_handler(_NoteId)
def _delete_note(cfg: HostConfig, user_id: str, args: _NoteId) -> dict[str, Any]:
    repo.delete_note(cfg, user_id, args.note_id)
    return {"deleted": True, "note_id": args.note_id}


@_handler(_Manifest)
def _notes_sync_manifest(cfg: HostConfig, user_id: str, args: _Manifest) -> dict[str, Any]:
    page = sync.manifest(
        cfg,
        user_id,
        args.source_system,
        args.source_workspace,
        **_only(args, exclude=("source_system", "source_workspace")),
    )
    return _json(page)


@_handler(_Upsert)
def _notes_sync_upsert(cfg: HostConfig, user_id: str, args: NoteUpsert) -> dict[str, Any]:
    result = sync.upsert(cfg, user_id, args, created_via="mcp")
    return _with_hygiene(cfg, user_id, _json(result), f"note:{result.note_id}")


@_handler(TombstoneBody)
def _notes_sync_tombstone(cfg: HostConfig, user_id: str, args: TombstoneBody) -> dict[str, Any]:
    result = sync.tombstone(
        cfg, user_id, args.source_system, args.source_workspace, args.source_doc_ids
    )
    return _json(result)


@_handler(UploadUrlBody)
def _request_attachment_upload(
    cfg: HostConfig, user_id: str, args: UploadUrlBody
) -> dict[str, Any]:
    ticket = attachments.request_upload(
        cfg, user_id, args.sha256, args.mime, args.size_bytes, args.filename
    )
    return UploadUrlResult.model_validate(ticket).model_dump(mode="json", exclude_none=True)


@_handler(_Proposal)
def _propose_note_enrichment(cfg: HostConfig, user_id: str, args: _Proposal) -> dict[str, Any]:
    if args.llm and not cfg.policy.llm_enrich:
        return {"error": "llm_disabled"}
    proposal = enrich.propose(
        cfg, user_id, args.note_id, llm=bool(args.llm), refresh=bool(args.refresh)
    )
    return _with_hygiene(cfg, user_id, _json(proposal), f"note:{args.note_id}")


@_handler(_Confirm)
def _confirm_note_enrichment(cfg: HostConfig, user_id: str, args: _Confirm) -> dict[str, Any]:
    body = ConfirmBody.model_validate(args.model_dump(exclude={"note_id"}, exclude_unset=True))
    result = _json(repo.confirm_links(cfg, user_id, args.note_id, body))
    # R1 owns the review recount (K§3); the REST route overlays it the same way.
    result.update(review.apply_confirm(cfg, user_id, args.note_id, body))
    return result


def _spec(
    name: str,
    handler: Callable[..., Any],
    model: type[BaseModel],
    description: str,
    *,
    writes: bool = False,
) -> ToolSpec:
    return ToolSpec(
        name=name,
        description=description,
        input_schema=_schema(model),
        handler=handler,
        writes=writes,
    )


NOTES_TOOLS: list[ToolSpec] = [
    _spec(
        "notes_capabilities",
        _notes_capabilities,
        _NoArgs,
        "What this app's notes store supports: attachments and their size/type limits, note kinds, "
        "source systems, link schemes, whether export, LLM enrichment, 'someday' ideas and "
        "hygiene are on. Call this before syncing anything, and respect the limits it reports.",
    ),
    _spec(
        "list_notes",
        _list_notes,
        _ListNotes,
        "List the user's notes, newest first, with filters. Returns summaries (no bodies), "
        "next_cursor for paging, sync_sources (last sync per source) and a hygiene block of "
        "problems worth telling the user about.",
    ),
    _spec(
        "get_note",
        _get_note,
        _NoteId,
        "Get one note with its body, attachments (signed URLs that expire within an hour) and "
        "confirmed links. The body is cut at 20,000 characters; truncated is true when it was. "
        "Includes a hygiene block for this note.",
    ),
    _spec(
        "get_notes_for_entity",
        _get_notes_for_entity,
        _GetNotesForEntity,
        "Find the notes linked to one entity of the host app (a piece, composer, technique...), "
        "with the links that matched. Set include_children to include its movements or pieces.",
    ),
    _spec(
        "create_note",
        _create_note,
        _CreateNote,
        "Write a new text note for the user. Text only: attachments are not accepted here. Pass "
        "source_system 'llm' and a unique source_doc_id to make retries safe (the same id returns "
        "the existing note, flagged already_existed).",
        writes=True,
    ),
    _spec(
        "update_note",
        _update_note,
        _UpdateNote,
        "Change a note's title, body, kind, person, date or place. Only the fields you send "
        "change; \"\" clears person, note_date and place. Imported notes (origin 'source') refuse "
        "title and body edits: edit them in their source instead.",
        writes=True,
    ),
    _spec(
        "delete_note",
        _delete_note,
        _NoteId,
        "Permanently delete a note and its links. Ask the user first. A note deleted at its "
        "source is tombstoned instead; use resolve_tombstone for those.",
        writes=True,
    ),
    _spec(
        "notes_sync_manifest",
        _notes_sync_manifest,
        _Manifest,
        "List what the server holds for one source workspace (id, path, content hash, attachment "
        "hashes), so a sync can tell new, changed and deleted notes apart. Page with after.",
    ),
    _spec(
        "notes_sync_upsert",
        _notes_sync_upsert,
        _Upsert,
        "Create or update one synced note, idempotent on (source_system, source_workspace, "
        "source_doc_id). Attachments are referenced by sha256 of blobs that already exist; any "
        "that do not are returned in missing_attachments: upload them with "
        "request_attachment_upload, then call again.",
        writes=True,
    ),
    _spec(
        "notes_sync_tombstone",
        _notes_sync_tombstone,
        TombstoneBody,
        "Tell the server the source deleted these notes. The notes and their links are kept, "
        "marked as deleted at the source; ids the server does not know come back in unknown.",
        writes=True,
    ),
    _spec(
        "request_attachment_upload",
        _request_attachment_upload,
        UploadUrlBody,
        "Get a one-time URL to upload an attachment's bytes. Returns status 'exists' (nothing to "
        "do) or 'upload' with a PUT URL: send the raw bytes with `curl -T <file> <upload_url>` "
        "and the same Content-Type. The URL expires in minutes.",
        writes=True,
    ),
    _spec(
        "propose_note_enrichment",
        _propose_note_enrichment,
        _Proposal,
        "Suggest links from a note to the user's library (pieces, composers, techniques), action "
        "items and unresolved mentions. Nothing is saved: show the suggestions to the user and "
        "let them choose. Returns the cached proposal unless refresh is true.",
    ),
    _spec(
        "confirm_note_enrichment",
        _confirm_note_enrichment,
        _Confirm,
        "Save the links, rejections and action items the user chose from a proposal. Never "
        "confirm without the user's explicit approval of what is being saved. Rejected pairs are "
        "not suggested again; deferred mentions stay for a later review.",
        writes=True,
    ),
]

TOOLS: list[ToolSpec] = [*NOTES_TOOLS, *hygiene_tools.TOOLS]


# ---------------------------------------------------------------------------------------------
# REST bindings: for hosts whose MCP layer calls REST (PT mcp_host.py via api_call)
# ---------------------------------------------------------------------------------------------


class RestBinding(NamedTuple):
    method: str
    path: str  # '/notes/{note_id}': {name} placeholders take the argument of that name
    query: tuple[str, ...] = ()  # arguments sent as query parameters
    body: bool = False  # True: every other argument goes in the JSON body
    fixed_query: Mapping[str, str] = {}  # always sent, e.g. include_hygiene (K§6.2)


_HYGIENE = {"include_hygiene": "true"}

REST_BINDINGS: dict[str, RestBinding] = {
    "notes_capabilities": RestBinding("GET", "/notes/capabilities"),
    "list_notes": RestBinding(
        "GET",
        "/notes",
        ("kind", "origin", "source_system", "q", "date_from", "date_to", "limit", "before"),
        fixed_query=_HYGIENE,
    ),
    "get_note": RestBinding("GET", "/notes/{note_id}", fixed_query=_HYGIENE),
    "get_notes_for_entity": RestBinding(
        "GET",
        "/notes/by-entity/{entity_type}/{entity_id}",
        ("limit", "include_children"),
    ),
    "create_note": RestBinding("POST", "/notes", body=True),
    "update_note": RestBinding("PATCH", "/notes/{note_id}", body=True),
    "delete_note": RestBinding("DELETE", "/notes/{note_id}"),
    "notes_sync_manifest": RestBinding(
        "GET", "/notes/sync/manifest", ("source_system", "source_workspace", "limit", "after")
    ),
    "notes_sync_upsert": RestBinding("POST", "/notes/sync/upsert", body=True, fixed_query=_HYGIENE),
    "notes_sync_tombstone": RestBinding("POST", "/notes/sync/tombstone", body=True),
    "request_attachment_upload": RestBinding("POST", "/attachments/upload-url", body=True),
    "propose_note_enrichment": RestBinding(
        "POST", "/notes/{note_id}/propose", ("llm", "refresh"), fixed_query=_HYGIENE
    ),
    "confirm_note_enrichment": RestBinding("POST", "/notes/{note_id}/confirm", body=True),
    # K§6.3
    "dismiss_issue": RestBinding("POST", "/hygiene/dismiss", body=True),
    "resolve_tombstone": RestBinding("POST", "/notes/{note_id}/resolve-tombstone", body=True),
    "apply_fix": RestBinding("POST", "/hygiene/apply-fix", body=True),
    "merge_entities": RestBinding("POST", "/hygiene/merge-entities", body=True),
}


class RestRequest(NamedTuple):
    method: str
    path: str
    params: dict[str, Any]
    json: dict[str, Any] | None


def rest_request(tool: str, args: Mapping[str, Any]) -> RestRequest:
    """Map a tool call to the REST request that serves it.

    A host calls `api_call(r.method, r.path, params=r.params, json=r.json)`. Query parameters
    left out or None are not sent. Raises KeyError for a tool without a binding. For update_note
    a "" in person/note_date/place becomes the null that clears the field on REST.
    """
    binding = REST_BINDINGS[tool]
    path_names = {name for _, name, _, _ in string.Formatter().parse(binding.path) if name}
    path = binding.path.format(**{name: args[name] for name in path_names})
    params: dict[str, Any] = dict(binding.fixed_query)
    for name in binding.query:
        if args.get(name) is not None:
            params[name] = args[name]
    body = None
    if binding.body:
        skip = path_names | set(binding.query)
        body = {name: value for name, value in args.items() if name not in skip}
        if tool == "update_note":  # the tool clears with "", the REST body with null
            body = {k: (None if k in _CLEARABLE and v == "" else v) for k, v in body.items()}
    return RestRequest(binding.method, path, params, body)


# ---------------------------------------------------------------------------------------------
# FastMCP registration
# ---------------------------------------------------------------------------------------------

_JSON_TYPES: dict[str, Any] = {
    "string": str,
    "integer": int,
    "number": float,
    "boolean": bool,
    "array": list[Any],
    "object": dict[str, Any],
}


def _python_type(prop: Mapping[str, Any]) -> Any:
    branches = [b for b in prop.get("anyOf", []) if not _is_null(b)]
    if "anyOf" in prop:
        return _python_type(branches[0]) if branches else Any
    if "enum" in prop:
        return Literal[tuple(prop["enum"])]  # type: ignore[valid-type]
    if "const" in prop:
        return Literal[prop["const"]]  # type: ignore[valid-type]
    return _JSON_TYPES.get(prop.get("type", ""), Any)


def _signature(spec: ToolSpec) -> inspect.Signature:
    """A signature that makes FastMCP derive `spec.input_schema` (names, types, required)."""
    required = set(spec.input_schema.get("required", []))
    params: list[inspect.Parameter] = []
    for name, prop in spec.input_schema.get("properties", {}).items():
        meta = {
            "description": prop.get("description"),
            "ge": prop.get("minimum"),
            "le": prop.get("maximum"),
        }
        kind = _python_type(prop)
        field = Field(**{k: v for k, v in meta.items() if v is not None})
        if name in required:
            params.append(
                inspect.Parameter(
                    name,
                    inspect.Parameter.KEYWORD_ONLY,
                    annotation=Annotated[kind, field],
                )
            )
        else:
            params.append(
                inspect.Parameter(
                    name,
                    inspect.Parameter.KEYWORD_ONLY,
                    default=None,
                    annotation=Annotated[kind | None, field],
                )
            )
    return inspect.Signature(params)


def _current_request(app: Any) -> Any:
    """The HTTP request behind the tool call being served, or None (stdio, no request).

    Understands the `fastmcp` package (get_http_request) and the official SDK (the request
    context on the server's Context). Principal.current_user_id receives whatever this finds.
    """
    try:
        deps = importlib.import_module("fastmcp.server.dependencies")
        return deps.get_http_request()
    except (ImportError, RuntimeError):
        pass
    get_context = getattr(app, "get_context", None)
    if get_context is not None:
        try:
            return get_context().request_context.request
        except (ValueError, LookupError, AttributeError):
            pass
    return None


def register_fastmcp(app: Any, cfg: HostConfig, wrap: Callable[..., Any] | None = None) -> None:
    """Register every tool in TOOLS on a FastMCP server (`fastmcp` or the `mcp` SDK's).

    Each tool resolves the caller with `cfg.principal.current_user_id(request)`, runs its handler
    and returns the dict. Handlers are blocking (they use `cfg.db`), so they must not run on the
    event loop: by default they run in a worker thread.

    `wrap(run) -> run2` lets the host choose how that blocking call is made instead (PT: its
    `_threaded_tool`). `run(user_id, tool_name, args) -> dict` is a plain function; `run2` takes
    the same arguments and may be sync or async. `wrap` returns the callable only: it must not
    register anything itself, this function does.
    """
    handlers = {spec.name: spec.handler for spec in TOOLS}

    def run(user_id: str, name: str, args: dict[str, Any]) -> Any:
        return handlers[name](cfg, user_id, **args)

    call = wrap(run) if wrap is not None else None

    def make_tool(spec: ToolSpec) -> Callable[..., Any]:
        async def tool(**kwargs: Any) -> Any:
            # Resolve the user here, on the loop thread, where the request context is visible.
            user_id = cfg.principal.current_user_id(_current_request(app))
            args = {k: v for k, v in kwargs.items() if v is not None}
            if call is None:
                return await asyncio.to_thread(run, user_id, spec.name, args)
            out = call(user_id, spec.name, args)
            return await out if inspect.isawaitable(out) else out

        tool.__name__ = spec.name
        tool.__doc__ = spec.description
        signature = _signature(spec)
        tool.__signature__ = signature  # type: ignore[attr-defined]
        # pydantic (fastmcp) reads annotations from here, not from the signature.
        tool.__annotations__ = {p.name: p.annotation for p in signature.parameters.values()}
        return tool

    for spec in TOOLS:
        app.tool(name=spec.name, description=spec.description)(make_tool(spec))
