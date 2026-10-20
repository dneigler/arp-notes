"""Hygiene framework (H1a, ga-mxal.30): detectors, keys, dismissals, block, routes, MCP tools."""

from __future__ import annotations

import json
import subprocess
import sys
from typing import Any

import pytest
from arp_notes import hygiene, mcp
from arp_notes.config import HostConfig
from arp_notes.hygiene import detect, routes
from arp_notes.hygiene import tools as hygiene_tools
from arp_notes.models import HygieneFix, HygieneIssue, HygieneSubject
from arp_notes.testing.fakedb import FakeDb
from fastapi import FastAPI
from fastapi.testclient import TestClient
from repo_support import OTHER, USER, add_blob, add_link, add_note, make_cfg


def age(db: FakeDb, table: str, column: str, row_id: int, days: int) -> None:
    db.run(
        f"UPDATE {table} SET {column} = CURRENT_TIMESTAMP - INTERVAL '{days} days' WHERE id = %s",
        [row_id],
    )


def tombstone(db: FakeDb, note_id: int) -> None:
    db.run("UPDATE notes SET deleted_at = CURRENT_TIMESTAMP WHERE id = %s", [note_id])


def pending_note(db: FakeDb, *, days: int, count: int = 3, user_id: str = USER, **cols: Any) -> int:
    note_id = add_note(db, user_id, review_pending=count, **cols)
    age(db, "notes", "proposed_at", note_id, days)
    return note_id


def keys(issues: list[HygieneIssue]) -> list[str]:
    return [issue.key for issue in issues]


@pytest.fixture
def cfg(notes_db: FakeDb) -> HostConfig:
    return make_cfg(notes_db)


class HostDetector:
    def __init__(self, issues: list[Any] | Exception) -> None:
        self.issues = issues
        self.calls: list[tuple[str, str]] = []

    def detect(self, user_id: str, scope: str) -> list[Any]:
        self.calls.append((user_id, scope))
        if isinstance(self.issues, Exception):
            raise self.issues
        return self.issues


def host_issue(key: str = "duplicate_entities:repertoire:18,19", **over: Any) -> HygieneIssue:
    data: dict[str, Any] = {
        "key": key,
        "kind": "duplicate_entities",
        "severity": "warn",
        "title": "Three Préludes look like the same book",
        "explanation": "Repertoire 18, 19 and 26 share a title and composer.",
        "subjects": [HygieneSubject(entity_type="repertoire", entity_id=18, label="Préludes")],
        "fixes": [
            HygieneFix(
                label="Preview the merge",
                tool="merge_entities",
                arguments={"entity_type": "repertoire", "keep_id": 18, "merge_ids": [19]},
                dry_run_first=True,
                reversible=False,
            )
        ],
        "detected_by": "host",
    }
    data.update(over)
    return HygieneIssue.model_validate(data)


# --- tombstoned_note -------------------------------------------------------------------------


def test_tombstoned_note_is_an_action_issue_with_keep_and_delete_fixes(
    cfg: HostConfig, notes_db: FakeDb
) -> None:
    gone = add_note(notes_db, title="Dave2025 masterclass")
    tombstone(notes_db, gone)
    add_note(notes_db, title="Still here")

    [issue] = detect.detect(cfg, USER)

    assert issue.key == f"tombstoned_note:note:{gone}"
    assert (issue.kind, issue.severity, issue.detected_by) == ("tombstoned_note", "action", "core")
    assert [(s.entity_type, s.entity_id, s.label) for s in issue.subjects] == [
        ("note", gone, "Dave2025 masterclass")
    ]
    assert "Dave2025 masterclass" in issue.explanation
    keep, delete = issue.fixes
    assert (keep.tool, keep.arguments, keep.reversible) == (
        "resolve_tombstone",
        {"note_id": gone, "action": "keep"},
        True,
    )
    assert (delete.tool, delete.arguments, delete.reversible) == (
        "resolve_tombstone",
        {"note_id": gone, "action": "delete"},
        False,
    )


# --- pending_review --------------------------------------------------------------------------


def test_pending_review_needs_a_count_and_a_proposal_older_than_seven_days(
    cfg: HostConfig, notes_db: FakeDb
) -> None:
    stale = pending_note(notes_db, days=8, count=2, title="Stale")
    pending_note(notes_db, days=6, title="Fresh")  # inside the week
    nothing = add_note(notes_db, title="Reviewed", review_pending=0)
    age(notes_db, "notes", "proposed_at", nothing, 30)  # old, but nothing is pending
    add_note(notes_db, title="Never proposed", review_pending=0)

    [issue] = detect.detect(cfg, USER)

    assert issue.key == f"pending_review:note:{stale}"
    assert (issue.kind, issue.severity) == ("pending_review", "info")
    assert "2 items" in issue.title
    assert [f.tool for f in issue.fixes] == ["propose_note_enrichment", "dismiss_issue"]
    assert issue.fixes[0].arguments == {"note_id": stale}
    assert issue.fixes[1].arguments == {"issue_key": issue.key}


def test_pending_review_skips_tombstoned_notes(cfg: HostConfig, notes_db: FakeDb) -> None:
    note_id = pending_note(notes_db, days=20)
    tombstone(notes_db, note_id)
    assert keys(detect.detect(cfg, USER)) == [f"tombstoned_note:note:{note_id}"]


# --- orphaned_links --------------------------------------------------------------------------


def test_orphaned_links_group_per_note_and_ignore_other_statuses(
    cfg: HostConfig, notes_db: FakeDb
) -> None:
    note_id = add_note(notes_db, title="Etudes")
    add_link(notes_db, note_id, "repertoire", 35, anchor="a", status="orphaned")
    add_link(notes_db, note_id, "movement", 3, anchor="b", status="orphaned")
    add_link(notes_db, note_id, "composer", 1, anchor="c", status="confirmed")
    add_link(notes_db, note_id, "technique", 7, anchor="d", status="rejected")

    [issue] = detect.detect(cfg, USER)

    assert issue.key == f"orphaned_links:note:{note_id}"
    assert (issue.kind, issue.severity) == ("orphaned_links", "warn")
    assert issue.title.startswith("2 links")
    assert issue.fixes[0].tool == "propose_note_enrichment"
    assert issue.fixes[0].arguments == {"note_id": note_id, "refresh": True}


def test_a_tombstoned_notes_orphans_are_left_to_the_tombstone_issue(
    cfg: HostConfig, notes_db: FakeDb
) -> None:
    note_id = add_note(notes_db)
    add_link(notes_db, note_id, "repertoire", 35, status="orphaned")
    tombstone(notes_db, note_id)
    assert keys(detect.detect(cfg, USER)) == [f"tombstoned_note:note:{note_id}"]


# --- unreferenced_blobs ----------------------------------------------------------------------


def test_unreferenced_blobs_need_zero_references_and_thirty_days(
    cfg: HostConfig, notes_db: FakeDb
) -> None:
    old_a, _ = add_blob(notes_db, text="old-a")
    old_b, _ = add_blob(notes_db, text="old-b", mime="application/pdf")
    young, _ = add_blob(notes_db, text="young")
    used, _ = add_blob(notes_db, text="used")
    for blob_id, days in ((old_a, 45), (old_b, 31), (young, 29), (used, 90)):
        age(notes_db, "blobs", "created_at", blob_id, days)
    note_id = add_note(notes_db)
    notes_db.run(
        "INSERT INTO note_attachments (note_id, blob_id, filename, ref_in_markdown)"
        " VALUES (%s, %s, 'u.png', '![[u.png]]')",
        [note_id, used],
    )

    [issue] = detect.detect(cfg, USER)

    assert issue.key == f"unreferenced_blobs:blob:{old_a},{old_b}"
    assert (issue.kind, issue.severity) == ("unreferenced_blobs", "info")
    assert sorted(s.entity_id for s in issue.subjects) == [old_a, old_b]
    assert all(s.entity_type == "blob" for s in issue.subjects)
    apply, dismiss = issue.fixes
    assert (apply.tool, apply.arguments, apply.dry_run_first, apply.reversible) == (
        "apply_fix",
        {"issue_key": issue.key, "fix_index": 0},
        True,
        False,
    )
    assert dismiss.tool == "dismiss_issue"


def test_unreferenced_blobs_key_changes_when_the_set_changes(
    cfg: HostConfig, notes_db: FakeDb
) -> None:
    first, _ = add_blob(notes_db, text="one")
    age(notes_db, "blobs", "created_at", first, 40)
    before = keys(detect.detect(cfg, USER))
    second, _ = add_blob(notes_db, text="two")
    age(notes_db, "blobs", "created_at", second, 40)
    after = keys(detect.detect(cfg, USER))
    assert before == [f"unreferenced_blobs:blob:{first}"]
    assert after == [f"unreferenced_blobs:blob:{first},{second}"]


def test_a_huge_blob_set_gets_a_short_stable_key(cfg: HostConfig, notes_db: FakeDb) -> None:
    for n in range(detect.MAX_KEY_IDS + 1):
        blob_id, _ = add_blob(notes_db, text=f"blob-{n}")
        age(notes_db, "blobs", "created_at", blob_id, 40)

    [issue] = detect.detect(cfg, USER)
    again = detect.detect(cfg, USER)[0]

    assert issue.key.startswith(f"unreferenced_blobs:blob:{detect.MAX_KEY_IDS + 1}+")
    assert len(issue.key) < 80
    assert again.key == issue.key
    assert len(issue.subjects) == detect.MAX_SUBJECTS
    assert issue.fixes[0].arguments["issue_key"] == issue.key


# --- unresolved_mentions ---------------------------------------------------------------------


def proposal(unresolved: Any) -> str:
    return json.dumps({"links": [], "ambiguous": [], "unresolved": unresolved})


def test_unresolved_mentions_come_from_the_cached_proposal(
    cfg: HostConfig, notes_db: FakeDb
) -> None:
    has = add_note(
        notes_db, title="Has some", proposal=proposal([{"mention": "WTC"}, {"mention": "X"}])
    )
    add_note(notes_db, title="Clean", proposal=proposal([]))
    add_note(notes_db, title="Never proposed")
    add_note(notes_db, title="Odd shape", proposal=json.dumps({"unresolved": "oops"}))
    gone = add_note(notes_db, title="Gone", proposal=proposal([{"mention": "Y"}]))
    tombstone(notes_db, gone)

    found = {i.key: i for i in detect.detect(cfg, USER) if i.kind == "unresolved_mentions"}

    assert list(found) == [f"unresolved_mentions:note:{has}"]
    issue = found[f"unresolved_mentions:note:{has}"]
    assert (issue.severity, issue.detected_by) == ("info", "core")
    assert issue.title.startswith("2 mentions")


# --- scope and isolation ---------------------------------------------------------------------


def test_note_scope_returns_only_that_notes_issues(cfg: HostConfig, notes_db: FakeDb) -> None:
    a = add_note(notes_db, title="A")
    b = add_note(notes_db, title="B")
    tombstone(notes_db, a)
    tombstone(notes_db, b)
    blob_id, _ = add_blob(notes_db)
    age(notes_db, "blobs", "created_at", blob_id, 60)

    assert keys(detect.detect(cfg, USER, f"note:{a}")) == [f"tombstoned_note:note:{a}"]
    assert sorted(keys(detect.detect(cfg, USER, "all"))) == sorted(
        [
            f"tombstoned_note:note:{a}",
            f"tombstoned_note:note:{b}",
            f"unreferenced_blobs:blob:{blob_id}",
        ]
    )
    assert detect.detect(cfg, USER, "note:99999") == []


@pytest.mark.parametrize("scope", ["", "note", "note:", "note:abc", "note:-1", "notes:1", "ALL"])
def test_bad_scopes_are_rejected(cfg: HostConfig, scope: str) -> None:
    with pytest.raises(detect.InvalidScope):
        detect.detect(cfg, USER, scope)
    with pytest.raises(hygiene.InvalidScope):
        hygiene.block(cfg, USER, scope)


def test_every_detector_is_scoped_to_the_user(cfg: HostConfig, notes_db: FakeDb) -> None:
    gone = add_note(notes_db, OTHER)
    tombstone(notes_db, gone)
    pending_note(notes_db, days=30, user_id=OTHER)
    orphan_note = add_note(notes_db, OTHER)
    add_link(notes_db, orphan_note, "repertoire", 1, user_id=OTHER, status="orphaned")
    add_note(notes_db, OTHER, proposal=proposal([{"mention": "Z"}]))
    blob_id, _ = add_blob(notes_db, OTHER)
    age(notes_db, "blobs", "created_at", blob_id, 60)

    assert detect.detect(cfg, USER) == []
    assert len(detect.detect(cfg, OTHER)) == 5


# --- host detectors --------------------------------------------------------------------------


def with_host(cfg: HostConfig, host: HostDetector) -> HostConfig:
    return HostConfig(
        db=cfg.db,
        principal=cfg.principal,
        storage=cfg.storage,
        signer=cfg.signer,
        schemes=cfg.schemes,
        policy=cfg.policy,
        hygiene=host,
    )


def test_host_issues_are_merged_and_marked_host(cfg: HostConfig, notes_db: FakeDb) -> None:
    gone = add_note(notes_db)
    tombstone(notes_db, gone)
    host = HostDetector([host_issue(detected_by="core")])  # a host cannot claim to be core

    block = hygiene.block(with_host(cfg, host), USER, "all")

    assert host.calls == [(USER, "all")]
    assert keys(block.issues) == [
        f"tombstoned_note:note:{gone}",
        "duplicate_entities:repertoire:18,19",
    ]
    assert [i.detected_by for i in block.issues] == ["core", "host"]


def test_host_detector_receives_the_scope(cfg: HostConfig) -> None:
    host = HostDetector([])
    hygiene.block(with_host(cfg, host), USER, "note:4")
    assert host.calls == [(USER, "note:4")]


def test_a_failing_host_detector_does_not_hide_core_issues(
    cfg: HostConfig, notes_db: FakeDb, caplog: pytest.LogCaptureFixture
) -> None:
    gone = add_note(notes_db)
    tombstone(notes_db, gone)

    block = hygiene.block(with_host(cfg, HostDetector(RuntimeError("boom"))), USER)

    assert keys(block.issues) == [f"tombstoned_note:note:{gone}"]
    assert "Hygiene.detect failed" in caplog.text


def test_invalid_host_issues_are_skipped(cfg: HostConfig) -> None:
    host = HostDetector([{"key": "nonsense"}, host_issue(), host_issue().model_dump()])
    block = hygiene.block(with_host(cfg, host), USER)
    assert keys(block.issues) == ["duplicate_entities:repertoire:18,19"]  # one key, once


def test_a_host_issue_cannot_shadow_a_core_key(cfg: HostConfig, notes_db: FakeDb) -> None:
    gone = add_note(notes_db)
    tombstone(notes_db, gone)
    clash = host_issue(f"tombstoned_note:note:{gone}", kind="tombstoned_note", title="host copy")
    block = hygiene.block(with_host(cfg, HostDetector([clash])), USER)
    [issue] = block.issues
    assert (issue.detected_by, issue.title) == ("core", "The source of “A note” was deleted")


# --- block: dismissals, ordering, cap --------------------------------------------------------


def test_block_sorts_most_severe_first(cfg: HostConfig, notes_db: FakeDb) -> None:
    pending = pending_note(notes_db, days=9)  # info
    orphan = add_note(notes_db)
    add_link(notes_db, orphan, "repertoire", 1, status="orphaned")  # warn
    gone = add_note(notes_db)
    tombstone(notes_db, gone)  # action

    block = hygiene.block(cfg, USER)

    assert [i.severity for i in block.issues] == ["action", "warn", "info"]
    assert keys(block.issues) == [
        f"tombstoned_note:note:{gone}",
        f"orphaned_links:note:{orphan}",
        f"pending_review:note:{pending}",
    ]
    assert (block.total, block.truncated) == (3, False)


def test_block_caps_at_ten_and_reports_the_total(cfg: HostConfig, notes_db: FakeDb) -> None:
    for _ in range(13):
        tombstone(notes_db, add_note(notes_db))

    block = hygiene.block(cfg, USER)

    assert len(block.issues) == 10
    assert (block.total, block.truncated) == (13, True)


def test_dismissing_filters_the_issue_and_the_total(cfg: HostConfig, notes_db: FakeDb) -> None:
    a = add_note(notes_db)
    b = add_note(notes_db)
    tombstone(notes_db, a)
    tombstone(notes_db, b)

    assert hygiene.dismiss(cfg, USER, f"tombstoned_note:note:{a}", "not now").dismissed is True

    block = hygiene.block(cfg, USER)
    assert keys(block.issues) == [f"tombstoned_note:note:{b}"]
    assert block.total == 1
    row = notes_db.run("SELECT user_id, reason FROM hygiene_dismissals")
    assert row == [{"user_id": USER, "reason": "not now"}]


def test_dismissal_is_idempotent_and_per_user(cfg: HostConfig, notes_db: FakeDb) -> None:
    key = "orphaned_links:note:5"
    hygiene.dismiss(cfg, USER, key, "first")
    hygiene.dismiss(cfg, USER, key, "second")
    hygiene.dismiss(cfg, OTHER, key)
    assert notes_db.run("SELECT user_id, reason FROM hygiene_dismissals ORDER BY id") == [
        {"user_id": USER, "reason": "first"},
        {"user_id": OTHER, "reason": None},
    ]
    assert hygiene.dismissed_keys(cfg, USER) == {key}


def test_a_dismissed_issue_returns_when_its_subjects_change(
    cfg: HostConfig, notes_db: FakeDb
) -> None:
    first, _ = add_blob(notes_db, text="one")
    age(notes_db, "blobs", "created_at", first, 40)
    [issue] = hygiene.block(cfg, USER).issues
    hygiene.dismiss(cfg, USER, issue.key)
    assert hygiene.block(cfg, USER).issues == []

    second, _ = add_blob(notes_db, text="two")
    age(notes_db, "blobs", "created_at", second, 40)

    assert keys(hygiene.block(cfg, USER).issues) == [f"unreferenced_blobs:blob:{first},{second}"]


def test_other_users_dismissals_do_not_hide_my_issues(cfg: HostConfig, notes_db: FakeDb) -> None:
    gone = add_note(notes_db)
    tombstone(notes_db, gone)
    hygiene.dismiss(cfg, OTHER, f"tombstoned_note:note:{gone}")
    assert len(hygiene.block(cfg, USER).issues) == 1


@pytest.mark.parametrize(
    "bad", ["", "nope", "tombstoned_note", "tombstoned_note:5", "made_up:note:5", "x" * 2000]
)
def test_dismiss_refuses_keys_no_issue_could_have(cfg: HostConfig, bad: str) -> None:
    with pytest.raises(hygiene.InvalidIssueKey):
        hygiene.dismiss(cfg, USER, bad)
    assert hygiene.dismissed_keys(cfg, USER) == set()


def test_keys_are_stable_across_runs(cfg: HostConfig, notes_db: FakeDb) -> None:
    gone = add_note(notes_db)
    tombstone(notes_db, gone)
    pending_note(notes_db, days=10)
    assert keys(hygiene.block(cfg, USER).issues) == keys(hygiene.block(cfg, USER).issues)


# --- resolve_tombstone -----------------------------------------------------------------------


def test_keep_dismisses_the_tombstone_issue_and_keeps_the_note(
    cfg: HostConfig, notes_db: FakeDb
) -> None:
    gone = add_note(notes_db)
    add_link(notes_db, gone, "repertoire", 35)
    tombstone(notes_db, gone)

    result = hygiene.resolve_tombstone(cfg, USER, gone, "keep")

    assert (result.note_id, result.action) == (gone, "keep")
    assert hygiene.block(cfg, USER).issues == []
    assert notes_db.run(
        "SELECT deleted_at IS NOT NULL AS gone FROM notes WHERE id = %s", [gone]
    ) == [{"gone": True}]
    assert notes_db.run("SELECT COUNT(*) AS n FROM note_links")[0]["n"] == 1
    # twice is fine
    assert hygiene.resolve_tombstone(cfg, USER, gone, "keep").action == "keep"


def test_delete_removes_the_note_and_cascades(cfg: HostConfig, notes_db: FakeDb) -> None:
    gone = add_note(notes_db)
    keep = add_note(notes_db, title="bystander")
    add_link(notes_db, gone, "repertoire", 35)
    tombstone(notes_db, gone)

    result = hygiene.resolve_tombstone(cfg, USER, gone, "delete")

    assert (result.note_id, result.action) == (gone, "delete")
    assert [r["id"] for r in notes_db.run("SELECT id FROM notes")] == [keep]
    assert notes_db.run("SELECT COUNT(*) AS n FROM note_links")[0]["n"] == 0
    assert hygiene.block(cfg, USER).total == 0


@pytest.mark.parametrize("action", ["keep", "delete"])
def test_a_live_note_cannot_be_resolved(cfg: HostConfig, notes_db: FakeDb, action: str) -> None:
    live = add_note(notes_db)
    with pytest.raises(hygiene.NotTombstoned):
        hygiene.resolve_tombstone(cfg, USER, live, action)  # type: ignore[arg-type]
    assert notes_db.run("SELECT COUNT(*) AS n FROM notes")[0]["n"] == 1
    assert hygiene.dismissed_keys(cfg, USER) == set()


@pytest.mark.parametrize("action", ["keep", "delete"])
def test_a_missing_or_foreign_note_is_not_found(
    cfg: HostConfig, notes_db: FakeDb, action: str
) -> None:
    theirs = add_note(notes_db, OTHER)
    tombstone(notes_db, theirs)
    for note_id in (99999, theirs):
        with pytest.raises(hygiene.repo.NoteNotFound):
            hygiene.resolve_tombstone(cfg, USER, note_id, action)  # type: ignore[arg-type]
    assert notes_db.run("SELECT COUNT(*) AS n FROM notes")[0]["n"] == 1


# --- REST routes -----------------------------------------------------------------------------


@pytest.fixture
def client(cfg: HostConfig) -> TestClient:
    app = FastAPI()
    app.include_router(routes.build_router(cfg))
    return TestClient(app)


def test_get_hygiene_returns_the_block(client: TestClient, notes_db: FakeDb) -> None:
    gone = add_note(notes_db)
    tombstone(notes_db, gone)

    body = client.get("/notes/hygiene").json()

    assert (body["total"], body["truncated"]) == (1, False)
    assert body["issues"][0]["key"] == f"tombstoned_note:note:{gone}"
    assert client.get("/notes/hygiene", params={"scope": f"note:{gone}"}).json()["total"] == 1
    other = add_note(notes_db)
    assert client.get("/notes/hygiene", params={"scope": f"note:{other}"}).json()["total"] == 0


def test_get_hygiene_errors(client: TestClient) -> None:
    bad = client.get("/notes/hygiene", params={"scope": "everything"})
    assert bad.status_code == 422
    assert bad.json()["error"] == "invalid_scope"
    missing = client.get("/notes/hygiene", params={"scope": "note:424242"})
    assert (missing.status_code, missing.json()["error"]) == (404, "not_found")


def test_hygiene_route_is_not_taken_for_a_note_id(client: TestClient) -> None:
    # The router may be mounted next to /notes/{note_id}; /notes/hygiene must reach us.
    assert client.get("/notes/hygiene").status_code == 200


def test_post_dismiss(client: TestClient, notes_db: FakeDb) -> None:
    gone = add_note(notes_db)
    tombstone(notes_db, gone)
    key = f"tombstoned_note:note:{gone}"

    response = client.post("/hygiene/dismiss", json={"issue_key": key, "reason": "later"})

    assert (response.status_code, response.json()) == (200, {"dismissed": True})
    assert client.get("/notes/hygiene").json()["total"] == 0
    bad = client.post("/hygiene/dismiss", json={"issue_key": "garbage"})
    assert (bad.status_code, bad.json()["error"]) == (422, "invalid_issue_key")
    assert client.post("/hygiene/dismiss", json={}).status_code == 422


def test_post_resolve_tombstone(client: TestClient, notes_db: FakeDb) -> None:
    gone = add_note(notes_db)
    live = add_note(notes_db)
    tombstone(notes_db, gone)

    kept = client.post(f"/notes/{gone}/resolve-tombstone", json={"action": "keep"})
    deleted = client.post(f"/notes/{gone}/resolve-tombstone", json={"action": "delete"})
    refused = client.post(f"/notes/{live}/resolve-tombstone", json={"action": "delete"})
    missing = client.post("/notes/424242/resolve-tombstone", json={"action": "keep"})
    unknown = client.post(f"/notes/{gone}/resolve-tombstone", json={"action": "archive"})

    assert (kept.status_code, kept.json()) == (200, {"note_id": gone, "action": "keep"})
    assert (deleted.status_code, deleted.json()) == (200, {"note_id": gone, "action": "delete"})
    assert (refused.status_code, refused.json()["error"]) == (409, "not_tombstoned")
    assert (missing.status_code, missing.json()["error"]) == (404, "not_found")
    assert unknown.status_code == 422


def test_the_config_free_router_stays_includable() -> None:
    assert routes.router is not None
    app = FastAPI()
    app.include_router(routes.router)  # H1b's routes mount here until they take a config


# --- MCP tools -------------------------------------------------------------------------------


def spec(name: str) -> mcp.ToolSpec:
    return next(s for s in mcp.TOOLS if s.name == name)


def test_the_two_h1a_tools_are_registered_as_writes() -> None:
    assert [s.name for s in hygiene_tools.TOOLS] == ["dismiss_issue", "resolve_tombstone"]
    assert mcp.TOOLS == [*mcp.NOTES_TOOLS, *hygiene_tools.TOOLS]
    assert all(s.writes for s in hygiene_tools.TOOLS)
    assert {s.name for s in hygiene_tools.TOOLS} <= set(mcp.REST_BINDINGS)


def test_tool_descriptions_tell_the_llm_to_explain_and_ask() -> None:
    for name in ("dismiss_issue", "resolve_tombstone"):
        text = spec(name).description.lower()
        assert "plain language" in text and "ask" in text
    assert "never pick 'delete' without an explicit yes" in spec("resolve_tombstone").description


def test_tool_input_schemas() -> None:
    dismiss = spec("dismiss_issue").input_schema
    assert dismiss["required"] == ["issue_key"]
    assert set(dismiss["properties"]) == {"issue_key", "reason"}
    resolve = spec("resolve_tombstone").input_schema
    assert sorted(resolve["required"]) == ["action", "note_id"]
    assert resolve["properties"]["action"]["enum"] == ["keep", "delete"]
    assert "title" not in resolve["properties"]["action"]


def test_dismiss_issue_tool(cfg: HostConfig, notes_db: FakeDb) -> None:
    handler = spec("dismiss_issue").handler
    assert handler(cfg, USER, issue_key="pending_review:note:3", reason="r") == {"dismissed": True}
    assert hygiene.dismissed_keys(cfg, USER) == {"pending_review:note:3"}
    assert handler(cfg, USER, issue_key="junk")["error"] == "invalid_issue_key"
    assert handler(cfg, USER)["error"] == "invalid_arguments"
    assert handler(cfg, USER, issue_key="pending_review:note:3", extra=1)["error"] == (
        "invalid_arguments"
    )


def test_resolve_tombstone_tool(cfg: HostConfig, notes_db: FakeDb) -> None:
    handler = spec("resolve_tombstone").handler
    gone = add_note(notes_db)
    live = add_note(notes_db)
    tombstone(notes_db, gone)

    assert handler(cfg, USER, note_id=live, action="delete")["error"] == "not_tombstoned"
    assert handler(cfg, USER, note_id=424242, action="keep")["error"] == "not_found"
    assert handler(cfg, USER, note_id=gone, action="archive")["error"] == "invalid_arguments"
    assert handler(cfg, USER, note_id=gone, action="delete") == {
        "note_id": gone,
        "action": "delete",
    }


def test_a_tombstone_issue_fixes_are_callable_tools(cfg: HostConfig, notes_db: FakeDb) -> None:
    """The fixes an issue carries must name tools that exist and accept those arguments."""
    gone = add_note(notes_db)
    tombstone(notes_db, gone)
    [issue] = hygiene.block(cfg, USER).issues
    names = {s.name for s in mcp.TOOLS}
    assert {fix.tool for fix in issue.fixes} <= names
    fix = issue.fixes[0]
    assert spec(fix.tool).handler(cfg, USER, **fix.arguments) == {"note_id": gone, "action": "keep"}


def test_every_core_fix_names_a_registered_tool(cfg: HostConfig, notes_db: FakeDb) -> None:
    pending_note(notes_db, days=9)
    orphan = add_note(notes_db)
    add_link(notes_db, orphan, "repertoire", 1, status="orphaned")
    add_note(notes_db, proposal=proposal([{"mention": "x"}]))
    blob_id, _ = add_blob(notes_db)
    age(notes_db, "blobs", "created_at", blob_id, 50)
    gone = add_note(notes_db)
    tombstone(notes_db, gone)
    known = {s.name for s in mcp.TOOLS} | {"apply_fix", "merge_entities"}  # H1b registers these

    issues = hygiene.block(cfg, USER).issues

    assert {i.kind for i in issues} == {
        "tombstoned_note",
        "pending_review",
        "orphaned_links",
        "unresolved_mentions",
        "unreferenced_blobs",
    }
    for issue in issues:
        assert issue.fixes, issue.key
        assert {f.tool for f in issue.fixes} <= known


def test_the_mcp_get_note_carries_the_real_block(cfg: HostConfig, notes_db: FakeDb) -> None:
    gone = add_note(notes_db, title="Gone")
    tombstone(notes_db, gone)
    note = spec("get_note").handler(cfg, USER, note_id=gone)
    assert note["hygiene"]["issues"][0]["key"] == f"tombstoned_note:note:{gone}"
    assert note["hygiene"]["total"] == 1


# --- import order ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "first",
    ["arp_notes.hygiene.tools", "arp_notes.mcp", "arp_notes.hygiene", "arp_notes.fastapi"],
)
def test_tools_and_mcp_agree_whichever_is_imported_first(first: str) -> None:
    code = (
        f"import importlib; importlib.import_module({first!r}); "
        "from arp_notes import mcp; from arp_notes.hygiene import tools; "
        "assert tools.TOOLS is tools.TOOLS; "
        "assert mcp.TOOLS == [*mcp.NOTES_TOOLS, *tools.TOOLS]; "
        "assert all(a is b for a, b in zip(mcp.TOOLS[-2:], tools.TOOLS)); "
        "print(len(mcp.TOOLS))"
    )
    done = subprocess.run(
        [sys.executable, "-I", "-c", code], capture_output=True, text=True, check=False
    )
    assert done.returncode == 0, done.stderr
    assert done.stdout.strip() == "15"
