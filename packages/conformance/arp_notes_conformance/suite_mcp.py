"""Conformance: MCP mode, the 17 tools (A.3, K§6.3).

Owner: C7b ga-mxal.38. The kit speaks MCP itself: JSON-RPC 2.0 over Streamable HTTP (one POST per
message, the answer is `application/json` or a single `text/event-stream` event), with the same
Bearer token as REST. It imports no MCP SDK, so a Node or Go host is held to the same checks.

Where the endpoint is: `$ARP_NOTES_MCP_URL` (an absolute URL, or a path on the host) when set,
else the first of `/mcp` and `<api prefix>/mcp` that answers `initialize`. A host with no MCP
endpoint has these checks skipped, with the paths tried.

What is proved: `tools/list` offers every A.3 name (the 13 notes tools, plus the 4 hygiene tools
of K§6.3 when `capabilities.hygiene` is true) each with a description and an object input schema;
`notes_capabilities` equals the REST answer; `list_notes` carries a hygiene block (and `get_note`
too) exactly when the host says hygiene is on; the write tools work and agree with REST; a failure
comes back as the REST error body (`{"error": code}`), not as a transport error.
"""

from __future__ import annotations

import itertools
import json
import os
from collections.abc import Callable
from typing import Any
from urllib.parse import urlsplit

import httpx

from .harness import UNKNOWN_ID, CheckFailed, CheckSkipped, Harness
from .suite_core import need, same

Check = Callable[[Harness], None]
CHECKS: list[tuple[str, Check]] = []

MCP_URL_ENV = "ARP_NOTES_MCP_URL"
PROTOCOL = "2025-03-26"

NOTES_TOOLS = (
    "notes_capabilities",
    "list_notes",
    "get_note",
    "get_notes_for_entity",
    "create_note",
    "update_note",
    "delete_note",
    "notes_sync_manifest",
    "notes_sync_upsert",
    "notes_sync_tombstone",
    "request_attachment_upload",
    "propose_note_enrichment",
    "confirm_note_enrichment",
)
HYGIENE_TOOLS = ("dismiss_issue", "resolve_tombstone", "apply_fix", "merge_entities")
WRITE_TOOLS = (
    "create_note",
    "update_note",
    "delete_note",
    "notes_sync_upsert",
    "notes_sync_tombstone",
    "request_attachment_upload",
    "confirm_note_enrichment",
    "dismiss_issue",
    "resolve_tombstone",
    "apply_fix",
    "merge_entities",
)


def check(name: str) -> Callable[[Check], Check]:
    def register(fn: Check) -> Check:
        CHECKS.append((name, fn))
        return fn

    return register


class McpError(CheckFailed):
    """The host's MCP endpoint broke JSON-RPC or MCP."""


class McpSession:
    """One MCP session: `initialize`, then any number of requests, as the harness's token."""

    def __init__(self, h: Harness, url: str) -> None:
        self.h = h
        self.url = url
        self.session_id: str | None = None
        self._ids = itertools.count(1)
        self.server_info: dict[str, Any] = {}

    def _post(self, message: dict[str, Any]) -> httpx.Response:
        headers = {
            "Authorization": f"Bearer {self.h.token}",
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
            "MCP-Protocol-Version": PROTOCOL,
        }
        if self.session_id:
            headers["Mcp-Session-Id"] = self.session_id
        return self.h.client.post(self.url, json=message, headers=headers)

    @staticmethod
    def _decode(response: httpx.Response, where: str) -> dict[str, Any]:
        kind = response.headers.get("content-type", "")
        text = response.text
        if kind.startswith("text/event-stream"):
            data = [line[5:].strip() for line in text.splitlines() if line.startswith("data:")]
            if not data:
                raise McpError(f"{where}: an event stream with no data event: {text[:200]!r}")
            text = data[-1]
        try:
            body = json.loads(text)
        except ValueError as exc:
            raise McpError(f"{where}: not JSON-RPC: {text[:200]!r}") from exc
        if not isinstance(body, dict) or body.get("jsonrpc") != "2.0":
            raise McpError(f"{where}: not a JSON-RPC 2.0 message: {text[:200]!r}")
        return body

    def request(self, method: str, params: dict[str, Any] | None = None) -> Any:
        """A JSON-RPC request; returns `result`, raises McpError on a JSON-RPC `error`."""
        message: dict[str, Any] = {"jsonrpc": "2.0", "id": next(self._ids), "method": method}
        if params is not None:
            message["params"] = params
        response = self._post(message)
        if response.status_code != 200:
            raise McpError(f"MCP {method}: HTTP {response.status_code}: {response.text[:200]}")
        self.session_id = response.headers.get("mcp-session-id") or self.session_id
        body = self._decode(response, f"MCP {method}")
        if body.get("id") != message["id"]:
            raise McpError(f"MCP {method}: answered id {body.get('id')!r}, asked {message['id']}")
        if "error" in body:
            raise McpError(f"MCP {method}: JSON-RPC error {body['error']}")
        if "result" not in body:
            raise McpError(f"MCP {method}: neither result nor error: {response.text[:200]}")
        return body["result"]

    def notify(self, method: str) -> None:
        response = self._post({"jsonrpc": "2.0", "method": method})
        need(
            response.status_code in (200, 202, 204),
            f"MCP {method} notification: HTTP {response.status_code}",
        )

    def initialize(self) -> None:
        result = self.request(
            "initialize",
            {
                "protocolVersion": PROTOCOL,
                "capabilities": {},
                "clientInfo": {"name": "arp-notes-conformance", "version": "0.1"},
            },
        )
        need(isinstance(result, dict) and "capabilities" in result, f"initialize result {result!r}")
        need(
            "tools" in result["capabilities"], "the server does not advertise the tools capability"
        )
        self.server_info = result.get("serverInfo") or {}
        self.notify("notifications/initialized")

    def tools(self) -> list[dict[str, Any]]:
        listed: list[dict[str, Any]] = []
        cursor: str | None = None
        for _ in range(20):
            result = self.request("tools/list", {"cursor": cursor} if cursor else {})
            listed += result["tools"]
            cursor = result.get("nextCursor")
            if not cursor:
                return listed
        raise McpError("tools/list paging never ended")

    def call(self, tool: str, **arguments: Any) -> dict[str, Any]:
        """tools/call -> the decoded result dict. A tool failure is `{"error": code, ...}`."""
        result = self.request("tools/call", {"name": tool, "arguments": arguments})
        payload = result.get("structuredContent")
        if payload is None:
            texts = [c["text"] for c in result.get("content", []) if c.get("type") == "text"]
            if not texts:
                raise McpError(f"tools/call {tool}: no structuredContent and no text content")
            try:
                payload = json.loads(texts[0])
            except ValueError:
                payload = (
                    {"error": "tool_error", "message": texts[0]} if result.get("isError") else None
                )
            if payload is None:
                raise McpError(f"tools/call {tool}: text content is not JSON: {texts[0][:200]!r}")
        if not isinstance(payload, dict):
            raise McpError(
                f"tools/call {tool}: result must be an object, got {type(payload).__name__}"
            )
        if result.get("isError") and "error" not in payload:
            payload = {"error": "tool_error", **payload}
        return payload


def endpoint(h: Harness) -> McpSession:
    """The host's MCP endpoint, initialised; skips the check when there is none."""
    explicit = os.environ.get(MCP_URL_ENV)
    candidates = [explicit] if explicit else ["/mcp", f"{h.prefix}/mcp"]
    tried: list[str] = []
    for url in candidates:
        session = McpSession(h, url)
        try:
            session.initialize()
        except (McpError, httpx.HTTPError) as exc:
            tried.append(f"{url} ({str(exc)[:80]})")
            if explicit:
                raise McpError(f"${MCP_URL_ENV}={explicit} does not speak MCP: {exc}") from exc
            continue
        return session
    raise CheckSkipped(
        f"no MCP endpoint answered initialize at {', '.join(tried)}; "
        f"set ${MCP_URL_ENV} to the host's MCP URL to run MCP mode"
    )


def usable(h: Harness, url: str) -> str:
    """An upload URL a client can PUT to. A.3 wants one an agent can `curl -T`, so a host should
    return it absolute (REST does); a path under the API mount is resolved here against the
    host the kit is already talking to."""
    if urlsplit(url).scheme or url.startswith(h.prefix + "/"):
        return url
    return h.prefix + url


def drop_nulls(value: Any) -> Any:
    """REST leaves unset optionals out and a tool may send them as null: both mean absent."""
    if isinstance(value, dict):
        return {k: drop_nulls(v) for k, v in value.items() if v is not None}
    if isinstance(value, list):
        return [drop_nulls(v) for v in value]
    return value


# -- checks ---------------------------------------------------------------------------------


@check("mcp.tools_list")
def tools_list(h: Harness) -> None:
    session = endpoint(h)
    tools = session.tools()
    names = [t["name"] for t in tools]
    need(len(names) == len(set(names)), f"tools/list repeats a name: {sorted(names)}")
    hygiene = h.capabilities["hygiene"]
    wanted = (*NOTES_TOOLS, *(HYGIENE_TOOLS if hygiene else ()))
    missing = [n for n in wanted if n not in names]
    need(
        not missing,
        f"tools/list lacks {missing}: A.3 freezes {len(NOTES_TOOLS)} notes tools"
        + (f" and K§6.3 adds {len(HYGIENE_TOOLS)} hygiene tools" if hygiene else "")
        + f" ({len(wanted)} in all); the host offers {sorted(names)}",
    )
    for tool in tools:
        if tool["name"] not in wanted:
            continue
        need(bool(tool.get("description")), f"tool {tool['name']} has no description")
        schema = tool.get("inputSchema")
        need(
            isinstance(schema, dict) and schema.get("type") == "object",
            f"tool {tool['name']} needs an inputSchema of type object, got {schema!r}",
        )
    by_name = {t["name"]: t for t in tools}
    same(
        sorted(by_name["get_note"]["inputSchema"].get("required", [])),
        ["note_id"],
        "get_note required arguments",
    )
    same(
        sorted(by_name["create_note"]["inputSchema"].get("required", [])),
        ["title"],
        "create_note required arguments",
    )


@check("mcp.capabilities_match_rest")
def capabilities_match_rest(h: Harness) -> None:
    session = endpoint(h)
    via_mcp = session.call("notes_capabilities")
    need("error" not in via_mcp, f"notes_capabilities failed: {via_mcp}")
    h.schemas.validate("Capabilities", via_mcp, "notes_capabilities result")
    same(drop_nulls(via_mcp), drop_nulls(h.capabilities), "notes_capabilities against REST")


@check("mcp.list_notes_carries_hygiene")
def list_notes_carries_hygiene(h: Harness) -> None:
    session = endpoint(h)
    note = h.create_note("Via MCP list")
    page = session.call("list_notes", q=h.tag)
    need("error" not in page, f"list_notes failed: {page}")
    h.schemas.validate("NoteList", page, "list_notes result")
    same([i["id"] for i in page["items"]], [note["id"]], "list_notes?q=<run id>")
    got = session.call("get_note", note_id=note["id"])
    need("error" not in got, f"get_note failed: {got}")
    same(got["id"], note["id"], "get_note id")
    same(got["truncated"], False, "get_note truncated flag on a short note")
    if h.capabilities["hygiene"]:
        for what, result in (("list_notes", page), ("get_note", got)):
            need(
                "hygiene" in result, f"{what} must carry a hygiene block when hygiene is on (K§6.2)"
            )
            h.schemas.validate("HygieneBlock", result["hygiene"], f"{what} hygiene")
    else:
        for what, result in (("list_notes", page), ("get_note", got)):
            need("hygiene" not in result, f"{what} has a hygiene block but hygiene is off")


@check("mcp.write_tools_agree_with_rest")
def write_tools_agree_with_rest(h: Harness) -> None:
    session = endpoint(h)
    made = session.call(
        "create_note",
        title=f"Made over MCP {h.tag}",
        body_md="Written by a client LLM.\n",
        kind=h.kind,
    )
    need("error" not in made, f"create_note failed: {made}")
    h.schemas.validate("Note", made, "create_note result")
    note_id = h.track(made["id"])
    over_rest = h.get_note(note_id)
    same(over_rest["title"], f"Made over MCP {h.tag}", "REST view of an MCP-created note")
    same(over_rest["body_md"], "Written by a client LLM.\n", "REST body of an MCP-created note")

    updated = session.call("update_note", note_id=note_id, body_md="Edited over MCP.\n")
    need("error" not in updated, f"update_note failed: {updated}")
    same(h.get_note(note_id)["body_md"], "Edited over MCP.\n", "REST body after update_note")

    doc = h.fixture.doc("scratch")
    upsert = h.upsert_body(doc, label="mcp-upsert")
    result = session.call("notes_sync_upsert", **upsert)
    need("error" not in result, f"notes_sync_upsert failed: {result}")
    h.schemas.validate("UpsertResult", result, "notes_sync_upsert result")
    h.track(result["note_id"])
    same(result["outcome"], "created", "notes_sync_upsert outcome")
    again = session.call("notes_sync_upsert", **upsert)
    same(again["outcome"], "unchanged", "notes_sync_upsert of the same bytes")

    manifest = session.call(
        "notes_sync_manifest",
        source_system=h.fixture.source_system,
        source_workspace=h.workspace,
    )
    need("error" not in manifest, f"notes_sync_manifest failed: {manifest}")
    h.schemas.validate("ManifestPage", manifest, "notes_sync_manifest result")
    same(
        [r["source_doc_id"] for r in manifest["items"]],
        [upsert["source_doc_id"]],
        "manifest over MCP",
    )
    gone = session.call(
        "notes_sync_tombstone",
        source_system=h.fixture.source_system,
        source_workspace=h.workspace,
        source_doc_ids=[upsert["source_doc_id"]],
    )
    need("error" not in gone, f"notes_sync_tombstone failed: {gone}")
    same(gone["tombstoned"], 1, "notes_sync_tombstone")
    need(h.get_note(result["note_id"])["deleted_at"] is not None, "REST does not see the tombstone")

    deleted = session.call("delete_note", note_id=note_id)
    need("error" not in deleted, f"delete_note failed: {deleted}")
    h.fails("GET", f"/notes/{note_id}", 404, "not_found")


@check("mcp.enrichment_tools")
def enrichment_tools(h: Harness) -> None:
    session = endpoint(h)
    doc = h.fixture.doc(h.fixture.recognised_document or "masterclass")
    note_id, _ = h.upsert(doc)
    proposal = session.call("propose_note_enrichment", note_id=note_id)
    need("error" not in proposal, f"propose_note_enrichment failed: {proposal}")
    h.schemas.validate("Proposal", proposal, "propose_note_enrichment result")
    same(proposal["note_id"], note_id, "Proposal.note_id over MCP")

    result = session.call(
        "confirm_note_enrichment",
        note_id=note_id,
        links=[],
        rejected=[],
        action_items=[],
        deferred=[{"mention": f"left for later {h.tag}"}],
    )
    need("error" not in result, f"confirm_note_enrichment failed: {result}")
    h.schemas.validate("ConfirmResult", result, "confirm_note_enrichment result")
    same(result["review_pending"], 1, "review_pending after deferring one item over MCP")
    same(h.get_note(note_id)["review_pending"], 1, "REST review_pending after the MCP confirm")


@check("mcp.attachment_upload_tool")
def attachment_upload_tool(h: Harness) -> None:
    from .suite_attach import accepted_mime, new_blob

    session = endpoint(h)
    if not h.capabilities["attachments"]:
        refused = session.call(
            "request_attachment_upload",
            sha256="0" * 64,
            mime="image/png",
            size_bytes=1,
            filename="x",
        )
        need(
            "error" in refused or refused.get("status") != "upload",
            "attachments are off but request_attachment_upload handed out an upload URL",
        )
        return
    blob = new_blob(h, "mcp")
    ticket = session.call("request_attachment_upload", **blob.request())
    need("error" not in ticket, f"request_attachment_upload failed: {ticket}")
    h.schemas.validate("UploadUrlResult", ticket, "request_attachment_upload result")
    same((ticket["status"], ticket["method"]), ("upload", "PUT"), "request_attachment_upload")
    put = h.client.put(
        usable(h, ticket["upload_url"]),
        content=blob.data,
        headers={"Content-Type": accepted_mime(h)},
    )
    h.expect_status(put, 201, "PUT to the URL request_attachment_upload returned")


@check("mcp.errors_are_rest_bodies")
def errors_are_rest_bodies(h: Harness) -> None:
    session = endpoint(h)
    missing = session.call("get_note", note_id=UNKNOWN_ID)
    same(missing.get("error"), "not_found", "get_note of an unknown note")
    refused = session.call("update_note", note_id=UNKNOWN_ID, title="x")
    same(refused.get("error"), "not_found", "update_note of an unknown note")
    bad = session.call("get_note", note_id="not-a-number")
    need("error" in bad, f"get_note with a bad argument must report an error, got {bad}")
    if not h.capabilities["llm_enrich"]:
        note = h.create_note("No LLM")
        llm = session.call("propose_note_enrichment", note_id=note["id"], llm=True)
        same(llm.get("error"), "llm_disabled", "propose_note_enrichment llm=true with llm off")
    doc = h.fixture.doc("scratch")
    note_id, _ = h.upsert(doc, label="mcp-readonly")
    readonly = session.call("update_note", note_id=note_id, body_md="no")
    same(readonly.get("error"), "read_only_import", "update_note of an imported body")
