"""REST: sync manifest, upsert and tombstone (C3, ga-mxal.10)."""

from __future__ import annotations

from typing import Any

from app_ref import BOB, Ref, ok, validate
from repo_support import add_blob, attachment_ref, sha, upsert_body

BODY = "# Etudes\n\nWork on Op. 10 nº 3 today, as Chopin said.\n"


def upsert(ref: Ref, doc_id: str = "d1", body: str = BODY, **over: Any) -> dict[str, Any]:
    payload = upsert_body(doc_id, body, **over).model_dump(mode="json", exclude_none=True)
    return ok(ref.post("/notes/sync/upsert", json=payload), "UpsertResult")


# -- upsert ---------------------------------------------------------------------------------


def test_upsert_creates_then_reports_unchanged_then_updated(ref: Ref) -> None:
    first = upsert(ref)
    assert first["outcome"] == "created" and first["missing_attachments"] == []
    assert first["links_orphaned"] == 0
    again = upsert(ref)
    assert again["outcome"] == "unchanged" and again["note_id"] == first["note_id"]
    edited = upsert(ref, body=BODY + "More.\n")
    assert edited["outcome"] == "updated" and edited["note_id"] == first["note_id"]
    note = ok(ref.get(f"/notes/{first['note_id']}"), "Note")
    assert note["origin"] == "source" and note["body_md"].endswith("More.\n")
    assert note["created_via"] == "cli"


def test_upsert_keeps_identity_across_a_rename(ref: Ref) -> None:
    first = upsert(ref, path="a/one.md")
    moved = upsert(ref, path="b/one.md")
    assert moved["note_id"] == first["note_id"] and moved["outcome"] == "unchanged"
    assert ok(ref.get(f"/notes/{first['note_id']}"))["source_path"] == "b/one.md"


def test_upsert_returns_the_blobs_the_server_still_needs(ref: Ref) -> None:
    _, have = add_blob(ref.db, text="have")
    want = sha("want")
    result = upsert(
        ref,
        attachments=[
            attachment_ref(have, "![[have.webp]]", "have.webp"),
            attachment_ref(want, "![[want.webp]]", "want.webp"),
        ],
    )
    assert result["outcome"] == "created"
    assert result["missing_attachments"] == [want]
    note = ok(ref.get(f"/notes/{result['note_id']}"))
    assert [a["sha256"] for a in note["attachments"]] == [have]


def test_upsert_rejects_a_malformed_hash(ref: Ref) -> None:
    payload = upsert_body("d1").model_dump(mode="json", exclude_none=True)
    payload["content_hash"] = "not-a-hash"
    assert ref.post("/notes/sync/upsert", json=payload).status_code == 422
    payload = upsert_body("d1").model_dump(mode="json", exclude_none=True)
    payload["attachments"] = [{**attachment_ref("XYZ", "![[a]]")}]
    assert ref.post("/notes/sync/upsert", json=payload).status_code == 422


def test_upsert_proposes_on_sync_with_search_only(ref: Ref) -> None:
    result = upsert(ref)
    note = ok(ref.get(f"/notes/{result['note_id']}"), "Note")
    assert note["review_pending"] >= 1 and note["proposed_at"]


def test_upsert_include_hygiene(ref: Ref) -> None:
    payload = upsert_body("d1").model_dump(mode="json", exclude_none=True)
    plain = ok(ref.post("/notes/sync/upsert", json=payload))
    assert "hygiene" not in plain
    asked = ok(ref.post("/notes/sync/upsert?include_hygiene=true", json=payload), "UpsertResult")
    assert asked["hygiene"]["issues"] == [] and asked["hygiene"]["total"] == 0


def test_upsert_is_per_user(ref: Ref) -> None:
    payload = upsert_body("d1").model_dump(mode="json", exclude_none=True)
    mine = ok(ref.post("/notes/sync/upsert", json=payload))
    theirs = ok(ref.post("/notes/sync/upsert", json=payload, headers=BOB))
    assert mine["note_id"] != theirs["note_id"] and theirs["outcome"] == "created"


def test_upsert_revives_a_tombstoned_note(ref: Ref) -> None:
    first = upsert(ref)
    ok(
        ref.post(
            "/notes/sync/tombstone",
            json={
                "source_system": "obsidian",
                "source_workspace": "Vault",
                "source_doc_ids": ["d1"],
            },
        ),
        "TombstoneResult",
    )
    back = upsert(ref)
    assert back["note_id"] == first["note_id"] and back["outcome"] == "updated"
    assert ok(ref.get(f"/notes/{first['note_id']}"))["deleted_at"] is None


# -- manifest -------------------------------------------------------------------------------


def test_manifest_lists_one_workspace(ref: Ref) -> None:
    for doc in ("a", "b", "c"):
        upsert(ref, doc)
    upsert(ref, "z", source_workspace="Other")
    page = ok(
        ref.get(
            "/notes/sync/manifest",
            params={"source_system": "obsidian", "source_workspace": "Vault"},
        ),
        "ManifestPage",
    )
    assert page["protocol"] == 1
    assert [row["source_doc_id"] for row in page["items"]] == ["a", "b", "c"]
    assert page["next_after"] is None
    row = page["items"][0]
    assert row["content_hash"] == sha(BODY) and row["source_path"] == "a.md"
    assert row["attachments"] == []


def test_manifest_pages_with_after(ref: Ref) -> None:
    for doc in ("a", "b", "c"):
        upsert(ref, doc)
    params = {"source_system": "obsidian", "source_workspace": "Vault", "limit": 2}
    first = ok(ref.get("/notes/sync/manifest", params=params), "ManifestPage")
    assert [r["source_doc_id"] for r in first["items"]] == ["a", "b"]
    assert first["next_after"] == "b"
    last = ok(ref.get("/notes/sync/manifest", params={**params, "after": "b"}))
    assert [r["source_doc_id"] for r in last["items"]] == ["c"] and last["next_after"] is None


def test_manifest_default_page_size_comes_from_the_policy(ref: Ref) -> None:
    for doc in ("a", "b", "c"):
        upsert(ref, doc)
    small = ref.with_policy(manifest_page_size=2)
    page = ok(
        small.get(
            "/notes/sync/manifest",
            params={"source_system": "obsidian", "source_workspace": "Vault"},
        )
    )
    assert len(page["items"]) == 2 and page["next_after"] == "b"


def test_manifest_parameters_are_checked(ref: Ref) -> None:
    assert ref.get("/notes/sync/manifest").status_code == 422
    base = {"source_system": "obsidian", "source_workspace": "Vault"}
    assert ref.get("/notes/sync/manifest", params={**base, "limit": 501}).status_code == 422
    assert ref.get("/notes/sync/manifest", params={**base, "limit": 0}).status_code == 422


def test_manifest_is_per_user_and_shows_tombstones(ref: Ref) -> None:
    upsert(ref, "a")
    base = {"source_system": "obsidian", "source_workspace": "Vault"}
    assert ok(ref.get("/notes/sync/manifest", params=base, headers=BOB))["items"] == []
    ok(ref.post("/notes/sync/tombstone", json={**base, "source_doc_ids": ["a"]}))
    row = ok(ref.get("/notes/sync/manifest", params=base))["items"][0]
    assert row["deleted_at"]


# -- tombstone ------------------------------------------------------------------------------


def test_tombstone_counts_and_names_the_unknown(ref: Ref) -> None:
    upsert(ref, "a")
    upsert(ref, "b")
    body = {
        "source_system": "obsidian",
        "source_workspace": "Vault",
        "source_doc_ids": ["a", "ghost"],
    }
    first = ok(ref.post("/notes/sync/tombstone", json=body), "TombstoneResult")
    assert first == {"tombstoned": 1, "unknown": ["ghost"]}
    second = ok(ref.post("/notes/sync/tombstone", json=body))
    assert second == {"tombstoned": 0, "unknown": ["ghost"]}
    listed = ok(ref.get("/notes"))
    assert [n["title"] for n in listed["items"]] == ["Note b"]


def test_tombstone_keeps_the_note_reachable_by_id(ref: Ref) -> None:
    made = upsert(ref, "a")
    ok(
        ref.post(
            "/notes/sync/tombstone",
            json={
                "source_system": "obsidian",
                "source_workspace": "Vault",
                "source_doc_ids": ["a"],
            },
        )
    )
    note = ok(ref.get(f"/notes/{made['note_id']}"), "Note")
    assert note["deleted_at"] and note["body_md"] == BODY
    assert note["review_pending"] == 0


def test_tombstone_only_touches_the_callers_notes(ref: Ref) -> None:
    upsert(ref, "a")
    body = {"source_system": "obsidian", "source_workspace": "Vault", "source_doc_ids": ["a"]}
    assert ok(ref.post("/notes/sync/tombstone", json=body, headers=BOB)) == {
        "tombstoned": 0,
        "unknown": ["a"],
    }
    assert ok(ref.get("/notes"))["items"][0]["deleted_at"] is None


def test_sync_bodies_are_validated(ref: Ref) -> None:
    assert ref.post("/notes/sync/tombstone", json={"source_system": "x"}).status_code == 422
    empty = {"source_system": "a", "source_workspace": "b", "source_doc_ids": []}
    validate("TombstoneBody", empty)
    assert ok(ref.post("/notes/sync/tombstone", json=empty)) == {"tombstoned": 0, "unknown": []}
