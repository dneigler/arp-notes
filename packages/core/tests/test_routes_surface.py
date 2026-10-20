"""The route table, the checked-in OpenAPI document and the mounted hygiene routes (C3)."""

from __future__ import annotations

import inspect
import json
from typing import Any

import pytest
from app_ref import API, Ref, fails, make_app, ok
from arp_notes import fastapi as notes_fastapi
from arp_notes import sync
from repo_support import USER, upsert_body

# A.2 + K§2 + K§6.3, as (method, path). The ids are FastAPI's {names}.
PRIVATE = {
    ("get", "/notes/capabilities"),
    ("get", "/notes/{note_id}/export"),
    ("get", "/notes"),
    ("post", "/notes"),
    ("get", "/notes/{note_id}"),
    ("patch", "/notes/{note_id}"),
    ("patch", "/notes/{note_id}/autosave"),
    ("delete", "/notes/{note_id}"),
    ("get", "/notes/by-entity/{entity_type}/{entity_id}"),
    ("get", "/notes/sync/manifest"),
    ("post", "/notes/sync/upsert"),
    ("post", "/notes/sync/tombstone"),
    ("post", "/notes/{note_id}/propose"),
    ("post", "/notes/{note_id}/confirm"),
    ("post", "/attachments/upload-url"),
    ("get", "/attachments/{blob_id}"),
    ("get", "/notes/hygiene"),
    ("post", "/hygiene/dismiss"),
    ("post", "/notes/{note_id}/resolve-tombstone"),
    ("post", "/hygiene/apply-fix"),
    ("post", "/hygiene/merge-entities"),
}
PUBLIC = {
    ("put", "/attachments/upload/{token}"),
    ("get", "/attachments/{blob_id}/content"),
}


def flatten(router: Any) -> list[Any]:
    """The APIRoutes of a router, whether this FastAPI nests included routers or not."""
    out: list[Any] = []
    for route in router.routes:
        nested = getattr(route, "original_router", None)
        out.extend(flatten(nested) if nested is not None else [route])
    return out


def table(router: Any) -> set[tuple[str, str]]:
    return {(m.lower(), r.path) for r in flatten(router) for m in r.methods}


def test_every_contract_endpoint_is_on_the_right_router(ref: Ref) -> None:
    private, public = notes_fastapi.build_routers(ref.cfg)
    assert table(private) == PRIVATE
    assert table(public) == PUBLIC


def test_routes_run_in_the_threadpool_except_the_upload_stream(ref: Ref) -> None:
    private, public = notes_fastapi.build_routers(ref.cfg)
    for route in flatten(private):
        assert not inspect.iscoroutinefunction(route.endpoint), route.path
    asyncs = {r.path for r in flatten(public) if inspect.iscoroutinefunction(r.endpoint)}
    assert asyncs == {"/attachments/upload/{token}"}


def test_the_routers_carry_no_prefix(ref: Ref) -> None:
    private, public = notes_fastapi.build_routers(ref.cfg, "/anything")
    assert all(not r.path.startswith("/anything") for r in [*flatten(private), *flatten(public)])


# -- OpenAPI --------------------------------------------------------------------------------


def test_the_checked_in_openapi_document_matches_the_routes() -> None:
    assert notes_fastapi.OPENAPI_PATH.read_text("utf-8") == notes_fastapi.render_openapi(), (
        "run: python -m arp_notes.fastapi"
    )
    assert notes_fastapi.main(["--check"]) == 0


def test_openapi_documents_every_endpoint_under_the_prefix() -> None:
    doc = json.loads(notes_fastapi.OPENAPI_PATH.read_text("utf-8"))
    documented = {
        (method, path.removeprefix(API)) for path, ops in doc["paths"].items() for method in ops
    }
    assert documented == PRIVATE | PUBLIC


def test_openapi_marks_the_private_operations_as_bearer_authenticated() -> None:
    doc = json.loads(notes_fastapi.OPENAPI_PATH.read_text("utf-8"))
    for path, ops in doc["paths"].items():
        for method, op in ops.items():
            public = (method, path.removeprefix(API)) in PUBLIC
            assert bool(op.get("security")) is not public, (method, path)


def test_openapi_describes_the_request_and_response_models() -> None:
    doc = json.loads(notes_fastapi.OPENAPI_PATH.read_text("utf-8"))
    ops = doc["paths"][f"{API}/notes/sync/upsert"]["post"]
    assert ops["requestBody"]["content"]["application/json"]["schema"]["$ref"].endswith(
        "/NoteUpsert"
    )
    ok_schema = ops["responses"]["200"]["content"]["application/json"]["schema"]
    assert ok_schema["$ref"].endswith("/UpsertResult")
    assert "201" in doc["paths"][f"{API}/notes"]["post"]["responses"]
    assert "204" in doc["paths"][f"{API}/notes/{{note_id}}"]["delete"]["responses"]


def test_the_document_is_deterministic() -> None:
    assert notes_fastapi.render_openapi() == notes_fastapi.render_openapi()


def test_main_writes_and_reports_drift(tmp_path: object, monkeypatch: pytest.MonkeyPatch) -> None:
    from pathlib import Path

    target = Path(str(tmp_path)) / "schemas" / "openapi.json"
    monkeypatch.setattr(notes_fastapi, "OPENAPI_PATH", target)
    assert notes_fastapi.main(["--check"]) == 1
    assert (
        notes_fastapi.main([]) == 0 and target.read_text("utf-8") == notes_fastapi.render_openapi()
    )
    assert notes_fastapi.main(["--check"]) == 0
    target.write_text("{}")
    assert notes_fastapi.main(["--check"]) == 1


# -- the hygiene routes are mounted and answer for the caller --------------------------------


def test_hygiene_routes_are_mounted(ref: Ref) -> None:
    block = ok(ref.get("/notes/hygiene"), "HygieneBlock")
    assert block == {"issues": [], "total": 0, "truncated": False}
    assert ref.post("/hygiene/apply-fix", json={}).status_code == 422
    assert ref.post("/hygiene/merge-entities", json={}).status_code == 422
    fails(ref.get("/notes/hygiene", params={"scope": "note:999"}), 404, "not_found")


def test_a_tombstone_can_be_kept_or_deleted_over_rest(ref: Ref) -> None:
    keep = sync.upsert(ref.cfg, USER, upsert_body("keep")).note_id
    gone = sync.upsert(ref.cfg, USER, upsert_body("gone")).note_id
    sync.tombstone(ref.cfg, USER, "obsidian", "Vault", ["keep", "gone"])
    issues = ok(ref.get("/notes/hygiene"), "HygieneBlock")["issues"]
    assert {i["kind"] for i in issues} == {"tombstoned_note"}
    kept = ok(
        ref.post(f"/notes/{keep}/resolve-tombstone", json={"action": "keep"}),
        "ResolveTombstoneResult",
    )
    assert kept == {"note_id": keep, "action": "keep"}
    deleted = ok(
        ref.post(f"/notes/{gone}/resolve-tombstone", json={"action": "delete"}),
        "ResolveTombstoneResult",
    )
    assert deleted["action"] == "delete"
    fails(ref.get(f"/notes/{gone}"), 404)
    assert ok(ref.get("/notes/hygiene"))["total"] == 0
    live = sync.upsert(ref.cfg, USER, upsert_body("live")).note_id
    fails(
        ref.post(f"/notes/{live}/resolve-tombstone", json={"action": "delete"}),
        409,
        "not_tombstoned",
    )


def test_a_dismissal_hides_the_issue(ref: Ref) -> None:
    note_id = sync.upsert(ref.cfg, USER, upsert_body("d1")).note_id
    sync.tombstone(ref.cfg, USER, "obsidian", "Vault", ["d1"])
    issue = ok(ref.get("/notes/hygiene"))["issues"][0]
    assert ok(ref.post("/hygiene/dismiss", json={"issue_key": issue["key"]}), "DismissResult") == {
        "dismissed": True
    }
    assert ok(ref.get("/notes/hygiene"))["total"] == 0
    fails(ref.post("/hygiene/dismiss", json={"issue_key": "nonsense"}), 422, "invalid_issue_key")
    assert note_id


def test_two_apps_can_mount_the_routers_independently(ref: Ref) -> None:
    from fastapi.testclient import TestClient

    other = TestClient(make_app(ref.cfg, "/v2"))
    assert (
        other.get("/v2/notes/capabilities", headers={"Authorization": "Bearer tok-u1"}).status_code
        == 200
    )
    assert other.get("/api/v1/notes/capabilities").status_code == 404


# -- PROTOCOL.md Part 3 ----------------------------------------------------------------------


def test_protocol_md_part_3_describes_the_routers() -> None:
    from pathlib import Path

    text = (Path(__file__).resolve().parents[3] / "PROTOCOL.md").read_text("utf-8")
    assert "# Part 3 · REST as built" in text
    for n in range(1, 9):
        assert f"## R§{n} · " in text, n
    part3 = text.split("# Part 3 · REST as built")[1]
    for needle in (
        "/attachments/upload/{token}",
        "X-Arp-Attachments",
        "export_disabled",
        "openapi.json",
    ):
        assert needle in part3, needle
    # every error code a route can return is in the R§3 table
    codes = {"attachments_disabled", "read_only_import", "hash_mismatch", "payload_too_large"}
    assert all(f"`{code}`" in part3 for code in codes)
