"""mcp: REST bindings and register_fastmcp (C4, ga-mxal.11)."""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Callable
from dataclasses import replace
from typing import Any, get_args, get_origin

import pytest
from arp_notes import mcp
from arp_notes.config import HostConfig
from arp_notes.ports import Policy
from repo_support import USER, FakeHooks, FakeScheme, FakeSigner, FakeStorage

# --- REST bindings ----------------------------------------------------------------------------


def test_every_tool_has_a_rest_binding() -> None:
    assert {s.name for s in mcp.TOOLS} <= set(mcp.REST_BINDINGS)
    # K§6.3 names are bound even before H1a/H1b land their specs
    assert {"dismiss_issue", "resolve_tombstone", "apply_fix", "merge_entities"} <= set(
        mcp.REST_BINDINGS
    )


@pytest.mark.parametrize("tool", [s.name for s in mcp.NOTES_TOOLS])
def test_binding_names_exist_in_the_tools_schema(tool: str) -> None:
    import string

    schema_props = set(next(s for s in mcp.TOOLS if s.name == tool).input_schema["properties"])
    binding = mcp.REST_BINDINGS[tool]
    path_names = {n for _, n, _, _ in string.Formatter().parse(binding.path) if n}
    assert path_names <= schema_props
    assert set(binding.query) <= schema_props


def test_rest_request_for_a_path_and_query_tool() -> None:
    req = mcp.rest_request(
        "get_notes_for_entity", {"entity_type": "composer", "entity_id": 3, "limit": 5}
    )
    assert req == mcp.RestRequest("GET", "/notes/by-entity/composer/3", {"limit": 5}, None)


def test_rest_request_always_asks_for_the_hygiene_block_on_reads() -> None:
    req = mcp.rest_request("list_notes", {"kind": "lecture", "q": None})
    assert req.params == {"include_hygiene": "true", "kind": "lecture"}
    assert mcp.rest_request("get_note", {"note_id": 4}).params == {"include_hygiene": "true"}
    assert mcp.rest_request("notes_capabilities", {}) == mcp.RestRequest(
        "GET", "/notes/capabilities", {}, None
    )


def test_rest_request_sends_remaining_arguments_as_the_body() -> None:
    req = mcp.rest_request("confirm_note_enrichment", {"note_id": 9, "links": [], "rejected": []})
    assert req == mcp.RestRequest("POST", "/notes/9/confirm", {}, {"links": [], "rejected": []})
    upsert = mcp.rest_request("notes_sync_upsert", {"source_doc_id": "d"})
    assert (upsert.method, upsert.path, upsert.json) == (
        "POST",
        "/notes/sync/upsert",
        {"source_doc_id": "d"},
    )
    assert upsert.params == {"include_hygiene": "true"}


def test_rest_request_propose_puts_flags_in_the_query() -> None:
    req = mcp.rest_request("propose_note_enrichment", {"note_id": 2, "llm": True, "refresh": True})
    assert req.path == "/notes/2/propose"
    assert req.params == {"include_hygiene": "true", "llm": True, "refresh": True}
    assert req.json is None


def test_rest_request_turns_an_empty_string_into_the_null_that_clears() -> None:
    req = mcp.rest_request("update_note", {"note_id": 1, "person": "", "title": "T"})
    assert req.method == "PATCH"
    assert req.json == {"person": None, "title": "T"}


def test_rest_request_for_an_unbound_tool_is_a_key_error() -> None:
    with pytest.raises(KeyError):
        mcp.rest_request("nope", {})


# --- register_fastmcp -------------------------------------------------------------------------


class FakeApp:
    """Records `app.tool(name=, description=)(fn)` like fastmcp and the mcp SDK do."""

    def __init__(self, request: Any = None) -> None:
        self.tools: dict[str, tuple[str, Callable[..., Any]]] = {}
        self._request = request

    def tool(self, name: str, description: str) -> Callable[[Callable[..., Any]], Any]:
        def register(fn: Callable[..., Any]) -> Callable[..., Any]:
            self.tools[name] = (description, fn)
            return fn

        return register

    def get_context(self) -> Any:  # the mcp SDK's shape
        outer = self

        class Ctx:
            class request_context:  # noqa: N801
                request = outer._request

        return Ctx


class RecordingPrincipal:
    def __init__(self) -> None:
        self.requests: list[Any] = []

    def current_user_id(self, request: Any) -> str:
        self.requests.append(request)
        return "caller"


@pytest.fixture
def recorded(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str, dict[str, Any]]]:
    """Swap every handler for one that records (tool, user_id, args)."""
    calls: list[tuple[str, str, dict[str, Any]]] = []

    def stub(name: str) -> Callable[..., dict[str, Any]]:
        def handler(cfg: HostConfig, user_id: str, **args: Any) -> dict[str, Any]:
            calls.append((name, user_id, args))
            return {"ok": name}

        return handler

    monkeypatch.setattr(mcp, "TOOLS", [replace(s, handler=stub(s.name)) for s in mcp.NOTES_TOOLS])
    return calls


def make_cfg_with(principal: Any) -> HostConfig:
    return HostConfig(
        db=None,  # type: ignore[arg-type]
        principal=principal,
        storage=FakeStorage(),
        signer=FakeSigner(),
        schemes=[FakeScheme()],
        policy=Policy(),
        hooks=FakeHooks(),
    )


def test_register_adds_every_tool_with_name_and_description(
    recorded: list[Any],
) -> None:
    app = FakeApp()
    mcp.register_fastmcp(app, make_cfg_with(RecordingPrincipal()))
    assert set(app.tools) == {s.name for s in mcp.TOOLS}
    for tool in mcp.TOOLS:
        description, fn = app.tools[tool.name]
        assert description == tool.description
        assert fn.__name__ == tool.name
        assert inspect.iscoroutinefunction(fn)


def test_the_registered_signature_carries_names_required_and_constraints(
    recorded: list[Any],
) -> None:
    app = FakeApp()
    mcp.register_fastmcp(app, make_cfg_with(RecordingPrincipal()))
    sig = inspect.signature(app.tools["get_notes_for_entity"][1])
    params = sig.parameters
    assert list(params) == ["entity_type", "entity_id", "limit", "include_children"]
    assert params["entity_type"].default is inspect.Parameter.empty
    assert params["limit"].default is None
    assert all(p.kind is inspect.Parameter.KEYWORD_ONLY for p in params.values())
    hints = app.tools["get_notes_for_entity"][1].__annotations__
    assert get_origin(hints["entity_id"]) is not None  # Annotated[int, Field(...)]
    assert get_args(hints["entity_id"])[0] is int


def test_a_call_resolves_the_user_and_runs_the_handler_in_a_worker_thread(
    recorded: list[Any],
) -> None:
    import threading

    principal = RecordingPrincipal()
    app = FakeApp(request="the-request")
    cfg = make_cfg_with(principal)
    threads: list[str] = []
    mcp.TOOLS[mcp.TOOLS.index(next(s for s in mcp.TOOLS if s.name == "get_note"))] = replace(
        next(s for s in mcp.TOOLS if s.name == "get_note"),
        handler=lambda c, u, **a: threads.append(threading.current_thread().name) or {"ok": 1},
    )
    mcp.register_fastmcp(app, cfg)
    out = asyncio.run(app.tools["get_note"][1](note_id=4))
    assert out == {"ok": 1}
    assert principal.requests == ["the-request"]
    assert threads and threads[0] != threading.main_thread().name


def test_none_arguments_are_dropped_before_the_handler(recorded: list[Any]) -> None:
    app = FakeApp()
    mcp.register_fastmcp(app, make_cfg_with(RecordingPrincipal()))
    asyncio.run(app.tools["update_note"][1](note_id=3, title="x", person=None, place=None))
    assert recorded == [("update_note", "caller", {"note_id": 3, "title": "x"})]


def test_wrap_chooses_how_the_blocking_call_is_made(recorded: list[Any]) -> None:
    app = FakeApp()
    seen: list[str] = []

    def wrap(run: Callable[..., Any]) -> Callable[..., Any]:
        def inline(user_id: str, name: str, args: dict[str, Any]) -> Any:
            seen.append(name)
            return run(user_id, name, args)

        return inline

    mcp.register_fastmcp(app, make_cfg_with(RecordingPrincipal()), wrap=wrap)
    out = asyncio.run(app.tools["list_notes"][1](kind="lecture"))
    assert out == {"ok": "list_notes"}
    assert seen == ["list_notes"]
    assert recorded == [("list_notes", "caller", {"kind": "lecture"})]


def test_wrap_may_return_an_async_callable(recorded: list[Any]) -> None:
    app = FakeApp()

    def wrap(run: Callable[..., Any]) -> Callable[..., Any]:
        async def threaded(user_id: str, name: str, args: dict[str, Any]) -> Any:
            return await asyncio.to_thread(run, user_id, name, args)

        return threaded

    mcp.register_fastmcp(app, make_cfg_with(RecordingPrincipal()), wrap=wrap)
    assert asyncio.run(app.tools["get_note"][1](note_id=1)) == {"ok": "get_note"}


def test_without_a_request_the_principal_gets_none(recorded: list[Any]) -> None:
    class Bare:
        """A server with no get_context (stdio, mcp v2): the principal must cope with None."""

        def __init__(self) -> None:
            self.tools: dict[str, Callable[..., Any]] = {}

        def tool(self, name: str, description: str) -> Callable[[Callable[..., Any]], Any]:
            def register(fn: Callable[..., Any]) -> Callable[..., Any]:
                self.tools[name] = fn
                return fn

            return register

    principal = RecordingPrincipal()
    app = Bare()
    mcp.register_fastmcp(app, make_cfg_with(principal))
    asyncio.run(app.tools["get_note"](note_id=1))
    assert principal.requests == [None]
    assert USER  # keep the shared import used


# --- request_attachment_upload: absolute upload_url (ga-mxal.50, R§1) ------------------------


class FakeRequest:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url


def _upload_tool(
    monkeypatch: pytest.MonkeyPatch,
    request: Any,
    returns: dict[str, Any] | None = None,
    **options: Any,
) -> Callable[..., Any]:
    answer = returns or {
        "status": "upload",
        "upload_url": "/attachments/upload/tok",
        "method": "PUT",
    }
    spec = next(s for s in mcp.NOTES_TOOLS if s.name == "request_attachment_upload")
    monkeypatch.setattr(mcp, "TOOLS", [replace(spec, handler=lambda cfg, user_id, **a: answer)])
    app = FakeApp(request=request)
    mcp.register_fastmcp(app, make_cfg_with(RecordingPrincipal()), **options)
    return app.tools["request_attachment_upload"][1]


def _call(tool: Callable[..., Any]) -> dict[str, Any]:
    return asyncio.run(tool(sha256="0" * 64, mime="image/png", size_bytes=3, filename="a.png"))


def test_upload_url_uses_public_base_url_and_the_api_prefix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tool = _upload_tool(
        monkeypatch,
        FakeRequest("http://internal:8000/"),
        public_base_url="https://notes.example.com/",
    )
    out = _call(tool)
    assert out["upload_url"] == "https://notes.example.com/api/v1/attachments/upload/tok"
    assert out["status"] == "upload"
    assert out["method"] == "PUT"


def test_upload_url_without_public_base_url_uses_the_request_origin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tool = _upload_tool(
        monkeypatch, FakeRequest("https://pt.example.com/"), api_prefix="/notes-api"
    )
    assert _call(tool)["upload_url"] == "https://pt.example.com/notes-api/attachments/upload/tok"


def test_upload_url_matches_what_rest_returns(monkeypatch: pytest.MonkeyPatch) -> None:
    from arp_notes.fastapi import _mounted

    tool = _upload_tool(monkeypatch, FakeRequest("https://pt.example.com/"))
    rest = _mounted("https://pt.example.com", "/api/v1", "/attachments/upload/tok")
    assert _call(tool)["upload_url"] == rest


def test_upload_url_is_left_alone_with_no_origin_to_use(monkeypatch: pytest.MonkeyPatch) -> None:
    # stdio: no request, no public_base_url
    tool = _upload_tool(monkeypatch, None)
    assert _call(tool)["upload_url"] == "/attachments/upload/tok"


def test_public_base_url_works_without_a_request(monkeypatch: pytest.MonkeyPatch) -> None:
    tool = _upload_tool(monkeypatch, None, public_base_url="https://notes.example.com")
    assert _call(tool)["upload_url"] == "https://notes.example.com/api/v1/attachments/upload/tok"


def test_an_existing_answer_has_no_upload_url_to_change(monkeypatch: pytest.MonkeyPatch) -> None:
    tool = _upload_tool(
        monkeypatch,
        FakeRequest("https://pt.example.com/"),
        returns={"status": "exists", "blob_id": 4},
    )
    assert _call(tool) == {"status": "exists", "blob_id": 4}


def test_other_tools_are_not_rewritten(
    recorded: list[Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    spec = next(s for s in mcp.NOTES_TOOLS if s.name == "get_note")
    monkeypatch.setattr(
        mcp, "TOOLS", [replace(spec, handler=lambda c, u, **a: {"upload_url": "/x"})]
    )
    app = FakeApp(request=FakeRequest("https://pt.example.com/"))
    mcp.register_fastmcp(app, make_cfg_with(RecordingPrincipal()))
    assert asyncio.run(app.tools["get_note"][1](note_id=1)) == {"upload_url": "/x"}
