"""H1b (ga-mxal.31): apply_fix and merge_entities, dry run -> confirm_token -> audited apply."""

from __future__ import annotations

import dataclasses
from typing import Any

import pytest
from arp_notes import mcp
from arp_notes.config import HostConfig
from arp_notes.hygiene import fixes, routes
from arp_notes.hygiene import tools as hygiene_tools
from arp_notes.models import MergePlan
from arp_notes.ports import Hooks
from arp_notes.repo import NotesError
from arp_notes.testing.fakedb import FakeDb
from fastapi import FastAPI
from fastapi.testclient import TestClient
from repo_support import OTHER, USER, add_blob, add_note, make_cfg


class AuditLog(Hooks):
    """Records on_event calls and hands out audit ids 500, 501, ..."""

    def __init__(self) -> None:
        super().__init__()
        self.events: list[tuple[str, str, Any, str]] = []
        self.on_event = self._on_event  # type: ignore[assignment]  # returns an id; port says None

    def _on_event(self, user_id: str, event_type: str, entity: Any, summary: str) -> int:
        self.events.append((user_id, event_type, entity, summary))
        return 500 + len(self.events) - 1


class HostMerge:
    """A host `Hygiene` with merge. The plan can be changed between calls via `rows`."""

    def __init__(self) -> None:
        self.rows = 2
        self.calls: list[tuple[Any, ...]] = []
        self.fail: Exception | None = None

    def detect(self, user_id: str, scope: str) -> list[Any]:
        return []

    def merge(
        self, user_id: str, entity_type: str, keep_id: int, merge_ids: Any, dry_run: bool
    ) -> MergePlan:
        self.calls.append((user_id, entity_type, keep_id, list(merge_ids), dry_run))
        if self.fail:
            raise self.fail
        return MergePlan.model_validate(
            {
                "entity_type": entity_type,
                "keep": keep_id,
                "merge": list(merge_ids),
                "moves": [
                    {"table": "practice_blocks", "column": "repertoire_id", "rows": self.rows}
                ],
                "conflicts": [],
                "warnings": ["Merged rows cannot be split again"],
                "snapshots": {"repertoire": [{"id": i, "title": "Préludes"} for i in merge_ids]},
            }
        )


class DumbHygiene:
    """A host with detect only (no merge)."""

    def detect(self, user_id: str, scope: str) -> list[Any]:
        return []


@pytest.fixture
def audit() -> AuditLog:
    return AuditLog()


@pytest.fixture
def host() -> HostMerge:
    return HostMerge()


@pytest.fixture
def cfg(notes_db: FakeDb, audit: AuditLog, host: HostMerge) -> HostConfig:
    return dataclasses.replace(make_cfg(notes_db, hooks=audit), hygiene=host)


@pytest.fixture(autouse=True)
def clean_tokens() -> None:
    fixes._used.clear()


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    now = [1_800_000_000]
    monkeypatch.setattr(fixes, "_now", lambda: now[0])
    return now


def merge(cfg: HostConfig, **over: Any) -> Any:
    args: dict[str, Any] = {"entity_type": "repertoire", "keep_id": 18, "merge_ids": [19, 26]}
    args.update(over)
    return fixes.merge_entities(cfg, USER, **args)


def expect(code: str, status: int, call: Any, *args: Any, **kwargs: Any) -> None:
    with pytest.raises(NotesError) as caught:
        call(*args, **kwargs)
    assert (caught.value.code, caught.value.status) == (code, status)


# --- merge_entities: dry run ------------------------------------------------------------------


def test_merge_without_a_token_is_a_dry_run(
    cfg: HostConfig, host: HostMerge, audit: AuditLog
) -> None:
    plan_a = merge(cfg)
    plan_b = merge(cfg, dry_run=False)  # no token: still a dry run

    for result in (plan_a, plan_b):
        assert result.plan.keep == 18 and result.plan.merge == [19, 26]
        assert result.plan.reversible is False
        assert result.plan.moves[0].rows == 2
        assert result.confirm_token and result.expires_at
    assert [call[-1] for call in host.calls] == [True, True]  # the host only ever planned
    assert audit.events == []


def test_the_dry_run_passes_the_request_principal_to_the_host(
    cfg: HostConfig, host: HostMerge
) -> None:
    merge(cfg)
    assert host.calls == [(USER, "repertoire", 18, [19, 26], True)]


def test_merge_ids_are_sorted_and_deduplicated(cfg: HostConfig, host: HostMerge) -> None:
    merge(cfg, merge_ids=[26, 19, 26])
    assert host.calls[0][3] == [19, 26]


def test_expires_at_is_ten_minutes_out(cfg: HostConfig, clock: list[int]) -> None:
    result = merge(cfg)
    assert result.expires_at == "2027-01-15T08:10:00"  # 1_800_000_000 + 600 s, UTC


@pytest.mark.parametrize(
    "over",
    [{"merge_ids": []}, {"merge_ids": [18]}, {"merge_ids": [18, 19]}, {"entity_type": ""}],
)
def test_a_nonsense_merge_is_refused(
    cfg: HostConfig, host: HostMerge, over: dict[str, Any]
) -> None:
    expect("invalid_merge", 422, merge, cfg, **over)
    assert host.calls == []


def test_a_host_that_cannot_merge_answers_not_supported(notes_db: FakeDb) -> None:
    for hygiene in (None, DumbHygiene()):
        bare = dataclasses.replace(make_cfg(notes_db, hooks=AuditLog()), hygiene=hygiene)
        expect("not_supported", 501, merge, bare)


def test_a_host_refusal_becomes_invalid_merge(cfg: HostConfig, host: HostMerge) -> None:
    host.fail = LookupError("repertoire 19 not found")
    expect("invalid_merge", 422, merge, cfg)


# --- merge_entities: apply --------------------------------------------------------------------


def test_apply_with_the_dry_run_token_merges_and_audits(
    cfg: HostConfig, host: HostMerge, audit: AuditLog
) -> None:
    token = merge(cfg).confirm_token

    result = merge(cfg, dry_run=False, confirm_token=token)

    assert result.model_dump() == {"applied": True, "audit_event_id": 500}
    assert host.calls[-1] == (USER, "repertoire", 18, [19, 26], False)
    [(user_id, event_type, entity, summary)] = audit.events
    assert (user_id, event_type) == (USER, "note_merge_applied")
    assert entity["entity_type"] == "repertoire" and entity["entity_id"] == 18
    assert entity["plan"]["moves"][0]["rows"] == 2
    assert [row["id"] for row in entity["plan"]["snapshots"]["repertoire"]] == [19, 26]
    assert "19, 26" in summary and "18" in summary


def test_a_token_with_dry_run_true_does_not_apply(cfg: HostConfig, host: HostMerge) -> None:
    token = merge(cfg).confirm_token
    result = merge(cfg, dry_run=True, confirm_token=token)
    assert result.plan.keep == 18
    assert all(call[-1] for call in host.calls)


def test_apply_is_refused_when_the_plan_changed(
    cfg: HostConfig, host: HostMerge, audit: AuditLog
) -> None:
    token = merge(cfg).confirm_token
    host.rows = 3  # a new practice block now points at a duplicate

    expect("plan_changed", 409, merge, cfg, dry_run=False, confirm_token=token)

    assert all(call[-1] for call in host.calls)
    assert audit.events == []


def test_a_token_is_single_use(cfg: HostConfig, host: HostMerge, audit: AuditLog) -> None:
    token = merge(cfg).confirm_token
    merge(cfg, dry_run=False, confirm_token=token)

    expect("token_used", 409, merge, cfg, dry_run=False, confirm_token=token)

    assert len([call for call in host.calls if not call[-1]]) == 1
    assert len(audit.events) == 1


def test_a_token_expires_after_ten_minutes(
    cfg: HostConfig, host: HostMerge, clock: list[int]
) -> None:
    token = merge(cfg).confirm_token
    clock[0] += 601

    expect("token_expired", 410, merge, cfg, dry_run=False, confirm_token=token)

    assert all(call[-1] for call in host.calls)


def test_a_token_at_the_expiry_second_still_applies(cfg: HostConfig, clock: list[int]) -> None:
    token = merge(cfg).confirm_token
    clock[0] += 600
    assert merge(cfg, dry_run=False, confirm_token=token).applied is True


@pytest.mark.parametrize("token", ["", "garbage", "12.", ".abc", "x1.abc", "-5.abc"])
def test_a_malformed_token_is_refused(cfg: HostConfig, token: str) -> None:
    expect("invalid_confirm_token", 422, merge, cfg, dry_run=False, confirm_token=token)


def test_a_forged_or_edited_token_is_plan_changed(cfg: HostConfig, host: HostMerge) -> None:
    stamp, _, mac = merge(cfg).confirm_token.partition(".")
    for token in (f"{stamp}.{'0' * len(mac)}", f"{int(stamp) + 3600}.{mac}"):  # extended TTL too
        expect("plan_changed", 409, merge, cfg, dry_run=False, confirm_token=token)
    assert all(call[-1] for call in host.calls)


def test_a_token_belongs_to_the_user_and_the_exact_merge(cfg: HostConfig, host: HostMerge) -> None:
    token = merge(cfg).confirm_token

    expect(
        "plan_changed",
        409,
        fixes.merge_entities,
        cfg,
        OTHER,
        "repertoire",
        18,
        [19, 26],
        False,
        token,
    )
    expect("plan_changed", 409, merge, cfg, merge_ids=[19], dry_run=False, confirm_token=token)
    expect("plan_changed", 409, merge, cfg, keep_id=19, merge_ids=[18], dry_run=False,
           confirm_token=token)  # fmt: skip
    assert all(call[-1] for call in host.calls)


def test_a_signer_secret_change_voids_tokens(cfg: HostConfig, notes_db: FakeDb) -> None:
    token = merge(cfg).confirm_token

    class Rotated:
        secret = b"another-secret"
        ttl_s = 3600

    rotated = dataclasses.replace(cfg, signer=Rotated())
    expect("plan_changed", 409, merge, rotated, dry_run=False, confirm_token=token)


def test_apply_needs_an_audit_log(notes_db: FakeDb, host: HostMerge) -> None:
    quiet = dataclasses.replace(make_cfg(notes_db), hygiene=host)
    token = merge(quiet).confirm_token  # planning needs no audit log
    expect("audit_unavailable", 501, merge, quiet, dry_run=False, confirm_token=token)
    assert all(call[-1] for call in host.calls)


def test_an_audit_hook_that_fails_does_not_undo_the_merge(
    cfg: HostConfig, host: HostMerge, audit: AuditLog
) -> None:
    def boom(*_: Any) -> int:
        raise RuntimeError("activity_log is down")

    audit.on_event = boom  # type: ignore[assignment]
    token = merge(cfg).confirm_token

    result = merge(cfg, dry_run=False, confirm_token=token)

    assert result.applied is True and result.audit_event_id == 0
    assert host.calls[-1][-1] is False


def test_a_hook_that_returns_no_id_audits_as_zero(cfg: HostConfig, audit: AuditLog) -> None:
    audit.on_event = lambda *_: None  # type: ignore[assignment,return-value]
    token = merge(cfg).confirm_token
    assert merge(cfg, dry_run=False, confirm_token=token).audit_event_id == 0


# --- apply_fix --------------------------------------------------------------------------------


def old_blob(db: FakeDb, text: str, user_id: str = USER, days: int = 40) -> int:
    blob_id, _ = add_blob(db, user_id, text=text)
    db.run(
        f"UPDATE blobs SET created_at = CURRENT_TIMESTAMP - INTERVAL '{days} days' WHERE id = %s",
        [blob_id],
    )
    return blob_id


def blob_ids(db: FakeDb, user_id: str = USER) -> list[int]:
    rows = db.run("SELECT id FROM blobs WHERE user_id = %s ORDER BY id", [user_id])
    return [row["id"] for row in rows]


def blob_issue_key(cfg: HostConfig) -> str:
    from arp_notes import hygiene

    [issue] = [i for i in hygiene.block(cfg, USER).issues if i.kind == "unreferenced_blobs"]
    return issue.key


class RecordingStorage:
    def __init__(self) -> None:
        self.deleted: list[tuple[str, str]] = []
        self.fail = False

    def put(self, *_: Any, **__: Any) -> str:
        return ""

    def open(self, *_: Any) -> Any:
        raise LookupError

    def delete(self, user_id: str, sha256: str) -> None:
        if self.fail:
            raise OSError("disk gone")
        self.deleted.append((user_id, sha256))


@pytest.fixture
def storage(cfg: HostConfig) -> RecordingStorage:
    return RecordingStorage()


@pytest.fixture
def blob_cfg(cfg: HostConfig, storage: RecordingStorage) -> HostConfig:
    return dataclasses.replace(cfg, storage=storage)


def test_apply_fix_dry_run_describes_the_deletion(blob_cfg: HostConfig, notes_db: FakeDb) -> None:
    a, b = old_blob(notes_db, "one"), old_blob(notes_db, "two")
    key = blob_issue_key(blob_cfg)

    result = fixes.apply_fix(blob_cfg, USER, key, 0)

    assert result["dry_run"] is True
    assert result["plan"]["blob_ids"] == [a, b]
    assert (result["plan"]["count"], result["plan"]["freed_bytes"]) == (2, 6)
    assert result["plan"]["reversible"] is False
    assert result["confirm_token"] and result["expires_at"]
    assert blob_ids(notes_db) == [a, b]  # nothing changed


def test_apply_fix_with_the_token_deletes_and_audits(
    blob_cfg: HostConfig, notes_db: FakeDb, storage: RecordingStorage, audit: AuditLog
) -> None:
    a, b = old_blob(notes_db, "one"), old_blob(notes_db, "two")
    keep, _ = add_blob(notes_db, text="fresh")  # under 30 days: not part of the issue
    mine = old_blob(notes_db, "theirs", OTHER)
    key = blob_issue_key(blob_cfg)
    token = fixes.apply_fix(blob_cfg, USER, key, 0)["confirm_token"]

    result = fixes.apply_fix(blob_cfg, USER, key, 0, token)

    assert result == {
        "applied": True,
        "result": {"deleted_blobs": 2, "freed_bytes": 6, "audit_event_id": 500},
    }
    assert blob_ids(notes_db) == [keep]
    assert blob_ids(notes_db, OTHER) == [mine]
    assert sorted(storage.deleted) == sorted(
        (USER, row)
        for row in [__import__("hashlib").sha256(t.encode()).hexdigest() for t in ("one", "two")]
    )
    [(user_id, event_type, entity, _)] = audit.events
    assert (user_id, event_type) == (USER, "note_hygiene_fix")
    assert entity["issue_key"] == key
    assert [row["id"] for row in entity["snapshots"]] == [a, b]
    assert entity["snapshots"][0]["mime"] == "image/webp"
    assert entity["plan"]["count"] == 2


def test_apply_fix_is_refused_when_a_note_started_using_a_blob(
    blob_cfg: HostConfig, notes_db: FakeDb, storage: RecordingStorage, audit: AuditLog
) -> None:
    a, b = old_blob(notes_db, "one"), old_blob(notes_db, "two")
    key = blob_issue_key(blob_cfg)
    token = fixes.apply_fix(blob_cfg, USER, key, 0)["confirm_token"]
    note_id = add_note(notes_db)
    notes_db.run(
        "INSERT INTO note_attachments (note_id, blob_id, filename, ref_in_markdown)"
        " VALUES (%s, %s, 'u.png', '![[u.png]]')",
        [note_id, a],
    )

    # The issue now covers {b} only, so its key changed and the old one is gone.
    expect("plan_changed", 409, fixes.apply_fix, blob_cfg, USER, key, 0, token)

    assert blob_ids(notes_db) == [a, b]
    assert storage.deleted == [] and audit.events == []


def test_apply_fix_is_refused_when_one_more_blob_became_unreferenced(
    blob_cfg: HostConfig, notes_db: FakeDb
) -> None:
    old_blob(notes_db, "one")
    key = blob_issue_key(blob_cfg)
    token = fixes.apply_fix(blob_cfg, USER, key, 0)["confirm_token"]
    old_blob(notes_db, "two")  # same issue kind, but a different key and plan

    expect("plan_changed", 409, fixes.apply_fix, blob_cfg, USER, key, 0, token)
    assert len(blob_ids(notes_db)) == 2


def test_apply_fix_rolls_back_when_a_blob_gets_used_during_the_apply(
    blob_cfg: HostConfig, notes_db: FakeDb, monkeypatch: pytest.MonkeyPatch
) -> None:
    a, b = old_blob(notes_db, "one"), old_blob(notes_db, "two")
    key = blob_issue_key(blob_cfg)
    token = fixes.apply_fix(blob_cfg, USER, key, 0)["confirm_token"]
    note_id = add_note(notes_db)
    real = fixes._blob_plan

    def plan_then_attach(*args: Any) -> dict[str, Any]:
        plan = real(*args)  # the re-plan sees both blobs unreferenced ...
        notes_db.run(  # ... and a note grabs one before the delete runs
            "INSERT INTO note_attachments (note_id, blob_id, filename, ref_in_markdown)"
            " VALUES (%s, %s, 'u.png', '![[u.png]]')",
            [note_id, b],
        )
        return plan

    monkeypatch.setattr(fixes, "_blob_plan", plan_then_attach)

    expect("plan_changed", 409, fixes.apply_fix, blob_cfg, USER, key, 0, token)

    assert blob_ids(notes_db) == [a, b]  # all or nothing


def test_apply_fix_token_is_single_use(blob_cfg: HostConfig, notes_db: FakeDb) -> None:
    old_blob(notes_db, "one")
    key = blob_issue_key(blob_cfg)
    token = fixes.apply_fix(blob_cfg, USER, key, 0)["confirm_token"]
    fixes.apply_fix(blob_cfg, USER, key, 0, token)

    # The issue is gone after the apply, which a replay also reports as a changed plan.
    expect("plan_changed", 409, fixes.apply_fix, blob_cfg, USER, key, 0, token)
    fixes._used.clear()
    expect("plan_changed", 409, fixes.apply_fix, blob_cfg, USER, key, 0, token)


def test_apply_fix_survives_a_storage_failure(
    blob_cfg: HostConfig, notes_db: FakeDb, storage: RecordingStorage
) -> None:
    old_blob(notes_db, "one")
    key = blob_issue_key(blob_cfg)
    token = fixes.apply_fix(blob_cfg, USER, key, 0)["confirm_token"]
    storage.fail = True

    result = fixes.apply_fix(blob_cfg, USER, key, 0, token)

    assert result["result"]["storage_errors"] == 1
    assert blob_ids(notes_db) == []  # the registry row is gone either way


def test_apply_fix_works_without_an_audit_log(notes_db: FakeDb) -> None:
    bare = make_cfg(notes_db)
    old_blob(notes_db, "one")
    key = blob_issue_key(bare)
    token = fixes.apply_fix(bare, USER, key, 0)["confirm_token"]
    result = fixes.apply_fix(bare, USER, key, 0, token)
    assert result["result"]["audit_event_id"] == 0


def test_apply_fix_errors(blob_cfg: HostConfig, notes_db: FakeDb) -> None:
    old_blob(notes_db, "one")
    key = blob_issue_key(blob_cfg)
    gone = add_note(notes_db)
    notes_db.run("UPDATE notes SET deleted_at = CURRENT_TIMESTAMP WHERE id = %s", [gone])

    expect("issue_not_found", 404, fixes.apply_fix, blob_cfg, USER, "unreferenced_blobs:blob:9", 0)
    expect("invalid_fix_index", 422, fixes.apply_fix, blob_cfg, USER, key, 5)
    expect("invalid_fix_index", 422, fixes.apply_fix, blob_cfg, USER, key, -1)
    expect("fix_not_applicable", 422, fixes.apply_fix, blob_cfg, USER, key, 1)  # dismiss_issue
    expect(
        "fix_not_applicable",
        422,
        fixes.apply_fix,
        blob_cfg,
        USER,
        f"tombstoned_note:note:{gone}",
        0,
    )
    expect("invalid_confirm_token", 422, fixes.apply_fix, blob_cfg, USER, key, 0, "nope")


def test_apply_fix_names_the_tool_to_call_instead(blob_cfg: HostConfig, notes_db: FakeDb) -> None:
    gone = add_note(notes_db)
    notes_db.run("UPDATE notes SET deleted_at = CURRENT_TIMESTAMP WHERE id = %s", [gone])
    with pytest.raises(fixes.FixNotApplicable) as caught:
        fixes.apply_fix(blob_cfg, USER, f"tombstoned_note:note:{gone}", 0)
    assert caught.value.extra == {
        "tool": "resolve_tombstone",
        "arguments": {"note_id": gone, "action": "keep"},
    }


def test_apply_fix_is_scoped_to_the_user(blob_cfg: HostConfig, notes_db: FakeDb) -> None:
    theirs = old_blob(notes_db, "theirs", OTHER)
    from arp_notes import hygiene

    [their_issue] = hygiene.block(blob_cfg, OTHER).issues

    expect("issue_not_found", 404, fixes.apply_fix, blob_cfg, USER, their_issue.key, 0)
    assert blob_ids(notes_db, OTHER) == [theirs]


# --- REST -------------------------------------------------------------------------------------


@pytest.fixture
def client(blob_cfg: HostConfig) -> TestClient:
    app = FastAPI()
    app.include_router(routes.build_router(blob_cfg))
    return TestClient(app)


def test_rest_merge_dry_run_then_apply(client: TestClient, host: HostMerge) -> None:
    body = {"entity_type": "repertoire", "keep_id": 18, "merge_ids": [19, 26]}

    planned = client.post("/hygiene/merge-entities", json=body)
    applied = client.post(
        "/hygiene/merge-entities",
        json={**body, "dry_run": False, "confirm_token": planned.json()["confirm_token"]},
    )
    replay = client.post(
        "/hygiene/merge-entities",
        json={**body, "dry_run": False, "confirm_token": planned.json()["confirm_token"]},
    )

    assert planned.status_code == 200
    assert set(planned.json()) == {"plan", "confirm_token", "expires_at"}
    assert planned.json()["plan"]["keep"] == 18
    assert (applied.status_code, applied.json()) == (200, {"applied": True, "audit_event_id": 500})
    assert (replay.status_code, replay.json()["error"]) == (409, "token_used")


def test_rest_merge_errors(client: TestClient, host: HostMerge) -> None:
    body = {"entity_type": "repertoire", "keep_id": 18, "merge_ids": [19]}
    planned = client.post("/hygiene/merge-entities", json=body).json()
    host.rows = 9

    changed = client.post(
        "/hygiene/merge-entities",
        json={**body, "dry_run": False, "confirm_token": planned["confirm_token"]},
    )
    invalid = client.post("/hygiene/merge-entities", json={**body, "merge_ids": [18]})
    unknown = client.post("/hygiene/merge-entities", json={"entity_type": "x"})

    assert (changed.status_code, changed.json()["error"]) == (409, "plan_changed")
    assert (invalid.status_code, invalid.json()["error"]) == (422, "invalid_merge")
    assert unknown.status_code == 422


def test_rest_merge_without_a_host_merge_is_501(notes_db: FakeDb) -> None:
    app = FastAPI()
    app.include_router(routes.build_router(make_cfg(notes_db)))
    response = TestClient(app).post(
        "/hygiene/merge-entities", json={"entity_type": "r", "keep_id": 1, "merge_ids": [2]}
    )
    assert (response.status_code, response.json()["error"]) == (501, "not_supported")


def test_rest_apply_fix_round_trip(
    client: TestClient, blob_cfg: HostConfig, notes_db: FakeDb
) -> None:
    old_blob(notes_db, "one")
    key = blob_issue_key(blob_cfg)

    dry = client.post("/hygiene/apply-fix", json={"issue_key": key, "fix_index": 0})
    done = client.post(
        "/hygiene/apply-fix",
        json={"issue_key": key, "fix_index": 0, "confirm_token": dry.json()["confirm_token"]},
    )
    missing = client.post(
        "/hygiene/apply-fix", json={"issue_key": "pending_review:note:1:", "fix_index": 0}
    )

    assert dry.status_code == 200 and dry.json()["dry_run"] is True
    assert (done.status_code, done.json()["applied"]) == (200, True)
    assert done.json()["result"]["deleted_blobs"] == 1
    assert (missing.status_code, missing.json()["error"]) == (404, "issue_not_found")
    assert blob_ids(notes_db) == []


# --- MCP --------------------------------------------------------------------------------------


def spec(name: str) -> mcp.ToolSpec:
    return next(s for s in mcp.TOOLS if s.name == name)


def test_there_are_17_tools_and_the_h1b_two_are_writes() -> None:
    assert len(mcp.TOOLS) == 17
    assert [s.name for s in hygiene_tools.TOOLS] == [
        "dismiss_issue",
        "resolve_tombstone",
        "apply_fix",
        "merge_entities",
    ]
    assert spec("apply_fix").writes and spec("merge_entities").writes
    assert {"apply_fix", "merge_entities"} <= set(mcp.REST_BINDINGS)


def test_h1b_tool_schemas() -> None:
    fix = spec("apply_fix").input_schema
    assert sorted(fix["required"]) == ["fix_index", "issue_key"]
    assert set(fix["properties"]) == {"issue_key", "fix_index", "confirm_token"}
    merged = spec("merge_entities").input_schema
    assert sorted(merged["required"]) == ["entity_type", "keep_id", "merge_ids"]
    assert merged["properties"]["dry_run"]["default"] is True
    assert merged["properties"]["merge_ids"]["minItems"] == 1


def test_h1b_descriptions_tell_the_llm_to_dry_run_explain_and_ask() -> None:
    for name in ("apply_fix", "merge_entities"):
        text = spec(name).description.lower()
        assert "plain language" in text and "ask" in text and "confirm_token" in text
        assert "plan_changed" in text and "dry run" in text or "dry_run" in text


def test_merge_entities_tool_round_trip(cfg: HostConfig) -> None:
    handler = spec("merge_entities").handler
    args = {"entity_type": "repertoire", "keep_id": 18, "merge_ids": [19, 26]}

    plan = handler(cfg, USER, **args)
    done = handler(cfg, USER, **args, dry_run=False, confirm_token=plan["confirm_token"])

    assert plan["plan"]["merge"] == [19, 26] and "dry_run" not in plan
    assert done == {"applied": True, "audit_event_id": 500}
    assert handler(cfg, USER, **args, dry_run=False, confirm_token="x")["error"] == (
        "invalid_confirm_token"
    )
    assert handler(cfg, USER, **{**args, "merge_ids": []})["error"] == "invalid_arguments"
    assert handler(cfg, USER, entity_type="r", keep_id=1, merge_ids=[1])["error"] == "invalid_merge"


def test_apply_fix_tool_runs_the_fix_an_issue_carries(
    blob_cfg: HostConfig, notes_db: FakeDb
) -> None:
    """The fix arguments a HygieneIssue carries are exactly what the tool accepts."""
    from arp_notes import hygiene

    old_blob(notes_db, "one")
    [issue] = [i for i in hygiene.block(blob_cfg, USER).issues if i.kind == "unreferenced_blobs"]
    fix = issue.fixes[0]
    handler = spec(fix.tool).handler

    dry = handler(blob_cfg, USER, **fix.arguments)
    done = handler(blob_cfg, USER, **fix.arguments, confirm_token=dry["confirm_token"])

    assert dry["dry_run"] is True
    assert done["applied"] is True and blob_ids(notes_db) == []
    assert handler(blob_cfg, USER, issue_key="nope:x:y", fix_index=0)["error"] == "issue_not_found"
