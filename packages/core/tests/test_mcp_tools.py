"""mcp: the 13 notes tool specs (A.3), their schemas and every handler (C4, ga-mxal.11)."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any, cast

import jsonschema
import pytest
from arp_notes import attachments, enrich, hygiene, mcp, repo, review, schemas
from arp_notes.config import HostConfig
from arp_notes.models import HygieneBlock, Proposal
from arp_notes.ports import Policy
from arp_notes.testing.fakedb import FakeDb
from repo_support import (
    OTHER,
    USER,
    FakeHooks,
    FakeScheme,
    add_blob,
    add_link,
    add_note,
    attachment_ref,
    make_cfg,
    sha,
    upsert_body,
)

pytestmark = pytest.mark.usefixtures("signed_urls")

EXAMPLES = Path(schemas.__file__).parent / "examples"

# A.3, in table order, with its R/W column.
A3: dict[str, bool] = {
    "notes_capabilities": False,
    "list_notes": False,
    "get_note": False,
    "get_notes_for_entity": False,
    "create_note": True,
    "update_note": True,
    "delete_note": True,
    "notes_sync_manifest": False,
    "notes_sync_upsert": True,
    "notes_sync_tombstone": True,
    "request_attachment_upload": True,
    "propose_note_enrichment": False,
    "confirm_note_enrichment": True,
}


def raw_db(cfg: HostConfig) -> FakeDb:
    return cast(FakeDb, cfg.db)


def spec(name: str) -> mcp.ToolSpec:
    return next(s for s in mcp.TOOLS if s.name == name)


def call(cfg: HostConfig, name: str, user_id: str = USER, **args: Any) -> dict[str, Any]:
    out = spec(name).handler(cfg, user_id, **args)
    assert isinstance(out, dict), f"{name} must return a dict, got {type(out).__name__}"
    return out


def example(name: str) -> dict[str, Any]:
    return json.loads((EXAMPLES / f"{name}.json").read_text("utf-8"))


@pytest.fixture
def scope_log(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Replace the hygiene block with one that records the scope it was asked for."""
    scopes: list[str] = []

    def block(cfg: HostConfig, user_id: str, scope: str = "all") -> HygieneBlock:
        scopes.append(scope)
        return HygieneBlock.model_validate({"issues": [], "total": 0, "truncated": False})

    monkeypatch.setattr(hygiene, "block", block)
    return scopes


# --- the specs --------------------------------------------------------------------------------


def test_notes_tools_are_exactly_the_13_a3_names_in_order() -> None:
    assert [s.name for s in mcp.NOTES_TOOLS] == list(A3)


def test_tools_compose_notes_then_hygiene_tools() -> None:
    from arp_notes.hygiene import tools as hygiene_tools

    assert mcp.TOOLS == [*mcp.NOTES_TOOLS, *hygiene_tools.TOOLS]
    names = [s.name for s in mcp.TOOLS]
    assert len(names) == len(set(names))
    # K§6.3: 13 + 4 once H1a/H1b have landed their specs.
    assert (
        set(A3)
        <= set(names)
        <= set(A3)
        | {
            "dismiss_issue",
            "resolve_tombstone",
            "apply_fix",
            "merge_entities",
        }
    )


@pytest.mark.parametrize("name", list(A3))
def test_write_flag_is_the_a3_rw_column(name: str) -> None:
    assert spec(name).writes is A3[name]


@pytest.mark.parametrize("name", list(A3))
def test_input_schema_is_valid_json_schema_2020_12(name: str) -> None:
    schema = spec(name).input_schema
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["type"] == "object"
    jsonschema.Draft202012Validator.check_schema(schema)


@pytest.mark.parametrize("name", list(A3))
def test_schema_is_tidy_for_an_llm(name: str) -> None:
    schema = spec(name).input_schema
    assert "title" not in schema or not isinstance(schema["title"], str)
    for prop_name, prop in schema["properties"].items():
        assert "default" not in prop or prop["default"] is not None, prop_name
        assert "title" not in prop or prop_name == "title" or not isinstance(prop["title"], str)
        assert "anyOf" not in prop or all(b.get("type") != "null" for b in prop["anyOf"]), prop_name


def test_descriptions_are_written_for_the_llm() -> None:
    for tool in mcp.NOTES_TOOLS:
        assert len(tool.description) > 60, tool.name
    assert "before syncing" in spec("notes_capabilities").description
    assert "Never confirm without the user" in spec("confirm_note_enrichment").description
    assert "Nothing is saved" in spec("propose_note_enrichment").description
    assert "20,000" in spec("get_note").description


def test_required_inputs_follow_a3() -> None:
    required = {name: set(spec(name).input_schema.get("required", [])) for name in A3}
    assert required["notes_capabilities"] == set()
    assert required["list_notes"] == set()
    assert required["get_note"] == {"note_id"}
    assert required["get_notes_for_entity"] == {"entity_type", "entity_id"}
    assert required["create_note"] == {"title"}
    assert required["update_note"] == {"note_id"}
    assert required["delete_note"] == {"note_id"}
    assert required["notes_sync_manifest"] == {"source_system", "source_workspace"}
    assert {"source_system", "source_workspace", "source_doc_id", "content_hash"} <= required[
        "notes_sync_upsert"
    ]
    assert required["notes_sync_tombstone"] == {
        "source_system",
        "source_workspace",
        "source_doc_ids",
    }
    assert required["request_attachment_upload"] == {"sha256", "mime", "size_bytes", "filename"}
    assert required["propose_note_enrichment"] == {"note_id"}
    assert required["confirm_note_enrichment"] == {"note_id"}


def test_a3_input_fields_are_all_present() -> None:
    props = {name: set(spec(name).input_schema["properties"]) for name in A3}
    assert props["list_notes"] >= {
        *("kind", "origin", "source_system", "q", "date_from", "date_to", "limit"),
    }
    assert props["create_note"] == {
        *("title", "body_md", "kind", "person", "note_date", "place"),
        *("source_system", "source_doc_id"),
    }
    assert props["update_note"] == {
        *("note_id", "title", "body_md", "kind", "person", "note_date", "place")
    }
    assert props["propose_note_enrichment"] >= {"note_id", "llm"}
    # ConfirmBody + note_id
    assert props["confirm_note_enrichment"] >= {"note_id", "links", "rejected", "action_items"}


def test_the_noteupsert_example_satisfies_the_upsert_schema() -> None:
    jsonschema.validate(example("NoteUpsert"), spec("notes_sync_upsert").input_schema)


def test_the_confirmbody_example_plus_note_id_satisfies_the_confirm_schema() -> None:
    args = {**example("ConfirmBody"), "note_id": 7}
    jsonschema.validate(args, spec("confirm_note_enrichment").input_schema)


# --- argument validation ----------------------------------------------------------------------


def test_bad_arguments_come_back_as_invalid_arguments(notes_cfg: HostConfig) -> None:
    out = call(notes_cfg, "list_notes", limit=0)
    assert out["error"] == "invalid_arguments"
    assert out["detail"][0]["field"] == "limit"


def test_unknown_and_missing_arguments_are_refused(notes_cfg: HostConfig) -> None:
    assert call(notes_cfg, "get_note")["error"] == "invalid_arguments"
    assert call(notes_cfg, "get_note", note_id=1, extra=1)["error"] == "invalid_arguments"
    assert call(notes_cfg, "notes_capabilities", x=1)["error"] == "invalid_arguments"


def test_a_notes_error_is_returned_as_its_rest_body(notes_cfg: HostConfig) -> None:
    assert call(notes_cfg, "get_note", note_id=999) == {
        "error": "not_found",
        "message": "note 999 not found",
    }


# --- notes_capabilities -----------------------------------------------------------------------


def test_capabilities_are_built_from_policy_schemes_and_judge(notes_db: FakeDb) -> None:
    class NamedJudge:
        name = "jev-choice>haiku"

        def judge(self, mention: Any, candidates: Any) -> Any:
            raise AssertionError

    policy = Policy(
        mime_allowlist=["image/webp", "application/pdf"],
        max_attachment_bytes=1234,
        llm_enrich=True,
        someday=True,
        propose_on_sync="judge",
    )
    cfg = replace(make_cfg(notes_db, policy=policy), judge=NamedJudge())
    out = call(cfg, "notes_capabilities")
    assert out["protocol"] == 1
    assert out["attachments"] is True
    assert out["mime_allowlist"] == ["image/webp", "application/pdf"]
    assert out["limits"]["max_attachment_bytes"] == 1234
    assert out["limits"]["upload_ticket_ttl_s"] == 900
    assert out["kinds"][0] == "masterclass" and "note" in out["kinds"]
    assert out["source_systems"] == ["obsidian", "notion", "apple_notes", "llm"]
    assert out["schemes"] == [
        {"prefix": "t", "entity_types": ["repertoire", "movement", "composer", "technique"]}
    ]
    assert (out["export"], out["llm_enrich"], out["someday"], out["hygiene"]) == (
        True,
        True,
        True,
        True,
    )
    assert out["propose_on_sync"] == "judge"
    assert out["judge"] == "jev-choice>haiku"


def test_capabilities_defaults_validate_against_the_schema(notes_cfg: HostConfig) -> None:
    out = call(notes_cfg, "notes_capabilities")
    schema = json.loads((Path(schemas.__file__).parent / "capabilities.json").read_text("utf-8"))
    jsonschema.validate(out, schema)
    assert out["judge"] is None
    assert out["mime_allowlist"] is None


# --- list_notes -------------------------------------------------------------------------------


def test_list_notes_pages_filters_and_carries_hygiene(
    notes_cfg: HostConfig, scope_log: list[str]
) -> None:
    for day in range(1, 6):
        add_note(
            raw_db(notes_cfg),
            title=f"N{day}",
            note_date=f"2026-10-0{day}",
            kind="lecture",
            origin="app",
        )
    add_note(raw_db(notes_cfg), title="Imported", origin="source", kind="note")
    add_note(raw_db(notes_cfg), OTHER, title="Not mine")

    first = call(notes_cfg, "list_notes", limit=2, kind="lecture")
    assert [n["title"] for n in first["items"]] == ["N5", "N4"]
    assert first["next_cursor"]
    assert first["hygiene"] == {"issues": [], "total": 0, "truncated": False}
    assert scope_log == ["all"]

    second = call(notes_cfg, "list_notes", limit=2, kind="lecture", before=first["next_cursor"])
    assert [n["title"] for n in second["items"]] == ["N3", "N2"]

    only_source = call(notes_cfg, "list_notes", origin="source")
    assert [n["title"] for n in only_source["items"]] == ["Imported"]
    assert call(notes_cfg, "list_notes", q="Not mine")["items"] == []


def test_list_notes_rejects_a_malformed_cursor(notes_cfg: HostConfig) -> None:
    assert call(notes_cfg, "list_notes", before="!!")["error"] == "invalid_cursor"


# --- get_note ---------------------------------------------------------------------------------


def test_get_note_returns_links_attachments_and_hygiene(
    notes_cfg: HostConfig, scope_log: list[str]
) -> None:
    note_id = add_note(raw_db(notes_cfg), title="Howat", body_md="# Intro\n\n![[a.webp]]\n")
    blob_id, _ = add_blob(raw_db(notes_cfg))
    raw_db(notes_cfg).run(
        "INSERT INTO note_attachments (note_id, blob_id, filename, ref_in_markdown)"
        " VALUES (%s, %s, 'a.webp', '![[a.webp]]')",
        [note_id, blob_id],
    )
    add_link(raw_db(notes_cfg), note_id, "repertoire", 35, anchor="intro")

    out = call(notes_cfg, "get_note", note_id=note_id)
    assert out["title"] == "Howat"
    assert out["truncated"] is False
    assert out["links"][0]["entity_label"] == "Études, Op.10"
    assert out["attachments"][0]["content_url"].startswith("/attachments/")
    assert out["hygiene"]["total"] == 0
    assert scope_log == [f"note:{note_id}"]


def test_get_note_cuts_the_body_at_20k_chars_and_says_so(notes_cfg: HostConfig) -> None:
    body = "x" * 25_000
    note_id = add_note(raw_db(notes_cfg), body_md=body)
    out = call(notes_cfg, "get_note", note_id=note_id)
    assert len(out["body_md"]) == mcp.NOTE_BODY_LIMIT == 20_000
    assert out["truncated"] is True
    assert out["body_md_chars"] == 25_000


def test_get_note_at_exactly_the_limit_is_not_truncated(notes_cfg: HostConfig) -> None:
    note_id = add_note(raw_db(notes_cfg), body_md="y" * 20_000)
    out = call(notes_cfg, "get_note", note_id=note_id)
    assert out["truncated"] is False
    assert len(out["body_md"]) == 20_000


def test_get_note_hides_other_users_notes(notes_cfg: HostConfig) -> None:
    theirs = add_note(raw_db(notes_cfg), OTHER)
    assert call(notes_cfg, "get_note", note_id=theirs)["error"] == "not_found"


def test_truncate_body_is_usable_by_rest_calling_hosts() -> None:
    cut = mcp.truncate_body({"body_md": "abcdef"}, limit=3)
    assert cut == {"body_md": "abc", "truncated": True, "body_md_chars": 6}
    assert mcp.truncate_body({"body_md": "ab"}, limit=3) == {"body_md": "ab", "truncated": False}


# --- hygiene block behaviour ------------------------------------------------------------------


def test_hygiene_off_leaves_the_block_out(notes_db: FakeDb, scope_log: list[str]) -> None:
    cfg = make_cfg(notes_db, policy=Policy(hygiene=False))
    note_id = add_note(notes_db)
    out = call(cfg, "get_note", note_id=note_id)
    assert "hygiene" not in out
    assert scope_log == []


def test_a_failing_detector_does_not_fail_the_read(
    notes_cfg: HostConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(*a: Any, **k: Any) -> HygieneBlock:
        raise RuntimeError("detector crashed")

    monkeypatch.setattr(hygiene, "block", boom)
    note_id = add_note(raw_db(notes_cfg))
    out = call(notes_cfg, "get_note", note_id=note_id)
    assert out["id"] == note_id
    assert "hygiene" not in out


# --- get_notes_for_entity ---------------------------------------------------------------------


def test_get_notes_for_entity_lists_linked_notes(notes_cfg: HostConfig) -> None:
    linked = add_note(raw_db(notes_cfg), title="About the Études")
    add_note(raw_db(notes_cfg), title="Unrelated")
    add_link(raw_db(notes_cfg), linked, "repertoire", 35)
    out = call(notes_cfg, "get_notes_for_entity", entity_type="repertoire", entity_id=35)
    assert [item["note"]["title"] for item in out["items"]] == ["About the Études"]
    assert out["items"][0]["links"][0]["entity_label"] == "Études, Op.10"


def test_get_notes_for_entity_can_include_children(notes_db: FakeDb) -> None:
    scheme = FakeScheme(
        {("repertoire", 35): "Études", ("movement", 12): "Nº 12"},
        {("repertoire", 35): [("movement", 12)]},
    )
    cfg = make_cfg(notes_db, scheme=scheme)
    note_id = add_note(notes_db, title="On nº 12")
    add_link(notes_db, note_id, "movement", 12)
    direct = call(cfg, "get_notes_for_entity", entity_type="repertoire", entity_id=35)
    assert direct["items"] == []
    wide = call(
        cfg, "get_notes_for_entity", entity_type="repertoire", entity_id=35, include_children=True
    )
    assert wide["items"][0]["links"][0]["via"] == {"entity_type": "movement", "entity_id": 12}


# --- create_note / update_note / delete_note --------------------------------------------------


def test_create_note_is_an_app_note_made_via_mcp(
    notes_cfg: HostConfig, fake_hooks: FakeHooks
) -> None:
    out = call(
        notes_cfg,
        "create_note",
        title="Reflection",
        body_md="# Today\n\nWent well.",
        kind="reflection",
        note_date="2026-10-19",
    )
    assert (out["origin"], out["created_via"], out["kind"]) == ("app", "mcp", "reflection")
    assert out["source_system"] is None
    assert out["body_md"].startswith("# Today")
    assert "note_created" in fake_hooks.names()


def test_create_note_defaults_the_kind_to_note(notes_cfg: HostConfig) -> None:
    assert call(notes_cfg, "create_note", title="Bare")["kind"] == "note"


def test_create_note_with_a_source_doc_id_is_retry_safe(notes_cfg: HostConfig) -> None:
    first = call(
        notes_cfg, "create_note", title="Idea", source_system="llm", source_doc_id="uuid-1"
    )
    assert (first["source_system"], first["source_doc_id"], first["origin"]) == (
        "llm",
        "uuid-1",
        "app",
    )
    assert "already_existed" not in first

    again = call(notes_cfg, "create_note", title="Idea (retry)", source_doc_id="uuid-1")
    assert again["id"] == first["id"]
    assert again["title"] == "Idea"
    assert again["already_existed"] is True
    assert raw_db(notes_cfg).run("SELECT count(*) AS n FROM notes")[0]["n"] == 1


def test_a_source_doc_id_is_per_user(notes_cfg: HostConfig) -> None:
    mine = call(notes_cfg, "create_note", title="A", source_doc_id="same")
    theirs = call(notes_cfg, "create_note", OTHER, title="B", source_doc_id="same")
    assert mine["id"] != theirs["id"]


def test_create_note_only_accepts_llm_as_source_system(notes_cfg: HostConfig) -> None:
    out = call(notes_cfg, "create_note", title="x", source_system="obsidian")
    assert out["error"] == "invalid_arguments"


def test_llm_notes_are_listed_under_the_llm_source(notes_cfg: HostConfig) -> None:
    call(notes_cfg, "create_note", title="From Claude", source_doc_id="u")
    call(notes_cfg, "create_note", title="Typed")
    out = call(notes_cfg, "list_notes", source_system="llm")
    assert [n["title"] for n in out["items"]] == ["From Claude"]


def test_update_note_changes_only_the_fields_sent(notes_cfg: HostConfig) -> None:
    note_id = add_note(raw_db(notes_cfg), title="Old", body_md="body", person="Roy", place="Paris")
    out = call(notes_cfg, "update_note", note_id=note_id, title="New")
    assert (out["title"], out["body_md"], out["person"], out["place"]) == (
        "New",
        "body",
        "Roy",
        "Paris",
    )
    assert out["version"] == 2


def test_update_note_clears_person_note_date_and_place_with_an_empty_string(
    notes_cfg: HostConfig,
) -> None:
    note_id = add_note(
        raw_db(notes_cfg), person="Roy", place="Paris", note_date="2026-10-01", body_md="keep"
    )
    out = call(notes_cfg, "update_note", note_id=note_id, person="", place="", note_date="")
    assert (out["person"], out["place"], out["note_date"]) == (None, None, None)
    assert out["body_md"] == "keep"


def test_update_note_edits_kind_on_an_imported_note_but_not_its_body(
    notes_cfg: HostConfig,
) -> None:
    note_id = add_note(raw_db(notes_cfg), origin="source", body_md="src")
    assert call(notes_cfg, "update_note", note_id=note_id, kind="masterclass")["kind"] == (
        "masterclass"
    )
    refused = call(notes_cfg, "update_note", note_id=note_id, body_md="mine")
    assert refused["error"] == "read_only_import"


def test_update_note_of_a_missing_note_is_not_found(notes_cfg: HostConfig) -> None:
    assert call(notes_cfg, "update_note", note_id=404, title="x")["error"] == "not_found"


def test_delete_note_removes_it_and_its_links(notes_cfg: HostConfig) -> None:
    note_id = add_note(raw_db(notes_cfg))
    add_link(raw_db(notes_cfg), note_id, "repertoire", 35)
    assert call(notes_cfg, "delete_note", note_id=note_id) == {"deleted": True, "note_id": note_id}
    assert raw_db(notes_cfg).run("SELECT 1 FROM notes WHERE id = %s", [note_id]) == []
    assert raw_db(notes_cfg).run("SELECT 1 FROM note_links WHERE note_id = %s", [note_id]) == []
    assert call(notes_cfg, "delete_note", note_id=note_id)["error"] == "not_found"


def test_delete_note_cannot_reach_another_users_note(notes_cfg: HostConfig) -> None:
    theirs = add_note(raw_db(notes_cfg), OTHER)
    assert call(notes_cfg, "delete_note", note_id=theirs)["error"] == "not_found"
    assert raw_db(notes_cfg).run("SELECT 1 FROM notes WHERE id = %s", [theirs])


# --- notes_sync_manifest / upsert / tombstone -------------------------------------------------


def upsert_args(doc_id: str = "d1", **over: Any) -> dict[str, Any]:
    return upsert_body(doc_id, **over).model_dump(mode="json", exclude_none=True)


def test_sync_upsert_creates_then_reports_unchanged(
    notes_cfg: HostConfig, scope_log: list[str]
) -> None:
    created = call(notes_cfg, "notes_sync_upsert", **upsert_args())
    assert created["outcome"] == "created"
    assert created["missing_attachments"] == []
    assert created["hygiene"]["total"] == 0
    assert scope_log == [f"note:{created['note_id']}"]
    row = raw_db(notes_cfg).run("SELECT created_via, origin FROM notes")[0]
    assert (row["created_via"], row["origin"]) == ("mcp", "source")

    again = call(notes_cfg, "notes_sync_upsert", **upsert_args())
    assert (again["outcome"], again["note_id"]) == ("unchanged", created["note_id"])


def test_sync_upsert_reports_attachments_that_must_be_uploaded_first(
    notes_cfg: HostConfig,
) -> None:
    _, have = add_blob(raw_db(notes_cfg), text="have")
    missing = sha("missing")
    args = upsert_args(
        body_md="![[a.webp]] ![[b.webp]]",
        attachments=[
            attachment_ref(have, "![[a.webp]]"),
            attachment_ref(missing, "![[b.webp]]"),
        ],
    )
    out = call(notes_cfg, "notes_sync_upsert", **args)
    assert out["missing_attachments"] == [missing]
    assert raw_db(notes_cfg).run("SELECT count(*) AS n FROM note_attachments")[0]["n"] == 1


def test_sync_upsert_rejects_a_bad_hash(notes_cfg: HostConfig) -> None:
    out = call(notes_cfg, "notes_sync_upsert", **{**upsert_args(), "content_hash": "nope"})
    assert out["error"] == "invalid_arguments"
    assert out["detail"][0]["field"] == "content_hash"


def test_sync_manifest_lists_and_pages(notes_cfg: HostConfig) -> None:
    for doc in ("a", "b", "c"):
        call(notes_cfg, "notes_sync_upsert", **upsert_args(doc))
    page = call(
        notes_cfg,
        "notes_sync_manifest",
        source_system="obsidian",
        source_workspace="Vault",
        limit=2,
    )
    assert [r["source_doc_id"] for r in page["items"]] == ["a", "b"]
    assert page["next_after"] == "b"
    rest = call(
        notes_cfg,
        "notes_sync_manifest",
        source_system="obsidian",
        source_workspace="Vault",
        after=page["next_after"],
    )
    assert [r["source_doc_id"] for r in rest["items"]] == ["c"]
    empty = call(
        notes_cfg, "notes_sync_manifest", source_system="obsidian", source_workspace="Other"
    )
    assert empty["items"] == []


def test_sync_tombstone_marks_notes_and_reports_unknown_ids(notes_cfg: HostConfig) -> None:
    made = call(notes_cfg, "notes_sync_upsert", **upsert_args("gone"))
    out = call(
        notes_cfg,
        "notes_sync_tombstone",
        source_system="obsidian",
        source_workspace="Vault",
        source_doc_ids=["gone", "never-seen"],
    )
    assert out == {"tombstoned": 1, "unknown": ["never-seen"]}
    gone = call(notes_cfg, "get_note", note_id=made["note_id"])
    assert gone["deleted_at"]


# --- request_attachment_upload ----------------------------------------------------------------


def test_request_upload_passes_the_call_to_attachments_and_drops_nulls(
    notes_cfg: HostConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[tuple[Any, ...]] = []

    def fake(cfg: HostConfig, user_id: str, *args: Any) -> dict[str, Any]:
        seen.append((user_id, *args))
        return {
            "status": "upload",
            "upload_url": "https://x/attachments/upload/tok",
            "method": "PUT",
            "expires_at": "2026-10-19T12:15:00",
        }

    monkeypatch.setattr(attachments, "request_upload", fake)
    digest = sha("img")
    out = call(
        notes_cfg,
        "request_attachment_upload",
        sha256=digest,
        mime="image/webp",
        size_bytes=3,
        filename="a.webp",
    )
    assert seen == [(USER, digest, "image/webp", 3, "a.webp")]
    assert out == {
        "status": "upload",
        "upload_url": "https://x/attachments/upload/tok",
        "method": "PUT",
        "expires_at": "2026-10-19T12:15:00",
    }


def test_request_upload_exists_has_only_the_blob_id(
    notes_cfg: HostConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        attachments, "request_upload", lambda *a, **k: {"status": "exists", "blob_id": 9}
    )
    out = call(
        notes_cfg,
        "request_attachment_upload",
        sha256=sha("x"),
        mime="image/png",
        size_bytes=1,
        filename="x.png",
    )
    assert out == {"status": "exists", "blob_id": 9}


def test_request_upload_validates_the_hash_before_calling(
    notes_cfg: HostConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    def never(*a: Any, **k: Any) -> dict[str, Any]:
        raise AssertionError("must not be called")

    monkeypatch.setattr(attachments, "request_upload", never)
    out = call(
        notes_cfg,
        "request_attachment_upload",
        sha256="ABC",
        mime="image/png",
        size_bytes=1,
        filename="x.png",
    )
    assert out["error"] == "invalid_arguments"


def test_a_notes_error_from_the_attachment_layer_reaches_the_client(
    notes_cfg: HostConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    class TooBig(repo.NotesError):
        status = 413
        code = "too_large"

    def refuse(*a: Any, **k: Any) -> dict[str, Any]:
        raise TooBig(max_attachment_bytes=10)

    monkeypatch.setattr(attachments, "request_upload", refuse)
    out = call(
        notes_cfg,
        "request_attachment_upload",
        sha256=sha("x"),
        mime="image/png",
        size_bytes=99,
        filename="x.png",
    )
    assert out == {"error": "too_large", "max_attachment_bytes": 10}


# --- propose_note_enrichment ------------------------------------------------------------------


def test_propose_returns_the_proposal_with_a_note_hygiene_block(
    notes_cfg: HostConfig, monkeypatch: pytest.MonkeyPatch, scope_log: list[str]
) -> None:
    seen: dict[str, Any] = {}
    proposal = Proposal.model_validate(example("Proposal"))

    def fake(cfg: HostConfig, user_id: str, note_id: int, **kw: Any) -> Proposal:
        seen.update(user_id=user_id, note_id=note_id, **kw)
        return proposal

    monkeypatch.setattr(enrich, "propose", fake)
    out = call(notes_cfg, "propose_note_enrichment", note_id=5)
    assert seen == {"user_id": USER, "note_id": 5, "llm": False, "refresh": False}
    hygiene_block = out.pop("hygiene")
    assert out == proposal.model_dump(mode="json", exclude={"hygiene"})
    assert hygiene_block["total"] == 0
    assert scope_log == ["note:5"]


def test_propose_forwards_refresh_and_llm(
    notes_db: FakeDb, monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg = make_cfg(notes_db, policy=Policy(llm_enrich=True))
    seen: dict[str, Any] = {}

    def fake(cfg: HostConfig, user_id: str, note_id: int, **kw: Any) -> Proposal:
        seen.update(kw)
        return Proposal.model_validate(example("Proposal"))

    monkeypatch.setattr(enrich, "propose", fake)
    call(cfg, "propose_note_enrichment", note_id=1, llm=True, refresh=True)
    assert seen == {"llm": True, "refresh": True}


def test_propose_with_llm_is_refused_when_the_host_has_it_off(
    notes_cfg: HostConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(enrich, "propose", lambda *a, **k: pytest.fail("must not be called"))
    assert call(notes_cfg, "propose_note_enrichment", note_id=1, llm=True) == {
        "error": "llm_disabled"
    }


def test_propose_for_a_missing_note_is_not_found(
    notes_cfg: HostConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    def missing(*a: Any, **k: Any) -> Proposal:
        raise repo.NoteNotFound("note 3 not found")

    monkeypatch.setattr(enrich, "propose", missing)
    assert call(notes_cfg, "propose_note_enrichment", note_id=3)["error"] == "not_found"


# --- confirm_note_enrichment ------------------------------------------------------------------


def test_confirm_creates_links_rejections_and_backlog_items(
    notes_cfg: HostConfig, fake_hooks: FakeHooks
) -> None:
    note_id = add_note(raw_db(notes_cfg), body_md="# Op.10 nº 12\n\nSlow it down.\n")
    out = call(
        notes_cfg,
        "confirm_note_enrichment",
        note_id=note_id,
        links=[
            {"entity_type": "repertoire", "entity_id": 35, "anchor": "op10-no-12", "quote": "x"},
            {"entity_type": "composer", "entity_id": 1},
        ],
        rejected=[{"entity_type": "technique", "entity_id": 7}],
        action_items=[{"text": "Slow it down", "lane": "practice", "link_index": 0}],
    )
    assert (out["links_created"], out["links_rejected"]) == (2, 1)
    assert out["backlog_created"] == [100]
    assert out["takeaways_created"] == 0
    assert out["someday_created"] == 0
    assert out["review_pending"] == 0
    statuses = {
        (r["entity_type"], r["status"])
        for r in raw_db(notes_cfg).run("SELECT entity_type, status FROM note_links")
    }
    assert statuses == {
        ("repertoire", "confirmed"),
        ("composer", "confirmed"),
        ("technique", "rejected"),
    }


def test_confirm_overlays_the_review_recount(
    notes_cfg: HostConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[Any] = []

    def recount(cfg: HostConfig, user_id: str, note_id: int, body: Any) -> dict[str, Any]:
        seen.append((user_id, note_id, len(body.links)))
        return {"review_pending": 3}

    monkeypatch.setattr(review, "apply_confirm", recount)
    note_id = add_note(raw_db(notes_cfg))
    out = call(
        notes_cfg,
        "confirm_note_enrichment",
        note_id=note_id,
        links=[{"entity_type": "composer", "entity_id": 1}],
    )
    assert out["review_pending"] == 3
    assert seen == [(USER, note_id, 1)]


def test_confirm_with_only_deferred_mentions_creates_nothing(notes_cfg: HostConfig) -> None:
    note_id = add_note(raw_db(notes_cfg))
    out = call(
        notes_cfg,
        "confirm_note_enrichment",
        note_id=note_id,
        deferred=[{"mention": "Debussy"}],
    )
    assert out["links_created"] == 0
    assert raw_db(notes_cfg).run("SELECT 1 FROM note_links") == []


def test_confirm_reports_the_repo_error_for_a_takeaway_without_a_link(
    notes_cfg: HostConfig,
) -> None:
    note_id = add_note(raw_db(notes_cfg))
    out = call(
        notes_cfg,
        "confirm_note_enrichment",
        note_id=note_id,
        takeaways=[{"anchor": "nowhere", "comment": "c"}],
    )
    assert out["error"] == "takeaway_needs_link"


def test_confirm_refuses_someday_when_the_host_does_not_keep_them(
    notes_cfg: HostConfig,
) -> None:
    note_id = add_note(raw_db(notes_cfg))
    out = call(
        notes_cfg,
        "confirm_note_enrichment",
        note_id=note_id,
        someday=[{"mention": "WTC Book 1"}],
    )
    assert out["error"] == "someday_unsupported"


def test_confirm_cannot_touch_another_users_note(notes_cfg: HostConfig) -> None:
    theirs = add_note(raw_db(notes_cfg), OTHER)
    out = call(
        notes_cfg,
        "confirm_note_enrichment",
        note_id=theirs,
        links=[{"entity_type": "composer", "entity_id": 1}],
    )
    assert out["error"] == "not_found"
    assert raw_db(notes_cfg).run("SELECT 1 FROM note_links") == []
