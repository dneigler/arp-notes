"""REST: capabilities, notes CRUD, list/by-entity, URLs and auth (C3, ga-mxal.10)."""

from __future__ import annotations

from typing import Any

import pytest
from app_ref import ALICE, API, BOB, ORIGIN, Ref, fails, ok, validate
from arp_notes import sync
from repo_support import USER, add_blob, add_link, add_note, attachment_ref, upsert_body


def new_note(ref: Ref, title: str = "Etudes", **body: Any) -> dict[str, Any]:
    return ok(ref.post("/notes", json={"title": title, **body}), "Note", 201)


# -- capabilities ---------------------------------------------------------------------------


def test_capabilities_describe_the_policy(ref: Ref) -> None:
    caps = ok(ref.get("/notes/capabilities"), "Capabilities")
    assert caps["protocol"] == 1
    assert caps["attachments"] is True
    assert caps["mime_allowlist"] is None
    assert caps["limits"]["max_attachment_bytes"] == 25 * 1024 * 1024
    assert caps["export"] is True
    assert caps["schemes"] == [
        {"prefix": "toy", "entity_types": ["repertoire", "movement", "composer", "technique"]}
    ]
    assert caps["judge"] is None
    assert caps["someday"] is False and caps["hygiene"] is True
    assert caps["propose_on_sync"] == "search"


def test_capabilities_follow_a_restrictive_policy(ref: Ref) -> None:
    tight = ref.with_policy(
        attachments=False, mime_allowlist=["application/pdf"], export=False, someday=True
    )
    caps = ok(tight.get("/notes/capabilities"), "Capabilities")
    assert caps["attachments"] is False
    assert caps["mime_allowlist"] == ["application/pdf"]
    assert caps["export"] is False and caps["someday"] is True


def test_capabilities_name_the_judge(ref: Ref) -> None:
    from dataclasses import replace

    from app_ref import make_app
    from fastapi.testclient import TestClient

    class Named:
        name = "jev-choice>haiku"

        def judge(self, mention: Any, candidates: Any) -> Any:
            raise AssertionError("not called")

    cfg = replace(ref.cfg, judge=Named())
    caps = ok(TestClient(make_app(cfg)).get(f"{API}/notes/capabilities", headers=ALICE))
    assert caps["judge"] == "jev-choice>haiku"


# -- auth -----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", "/notes"),
        ("get", "/notes/capabilities"),
        ("get", "/notes/1"),
        ("post", "/notes"),
        ("get", "/notes/sync/manifest?source_system=a&source_workspace=b"),
        ("post", "/attachments/upload-url"),
        ("get", "/attachments/1"),
        ("get", "/notes/hygiene"),
        ("get", "/notes/1/export"),
    ],
)
def test_private_routes_need_the_principal(ref: Ref, method: str, path: str) -> None:
    response = getattr(ref.client, method)(API + path)
    assert response.status_code == 401


def test_private_routes_reject_an_unknown_token(ref: Ref) -> None:
    bad = {"Authorization": "Bearer nope"}
    assert ref.client.get(f"{API}/notes", headers=bad).status_code == 401


# -- create / get / patch / delete ----------------------------------------------------------


def test_create_then_get(ref: Ref) -> None:
    made = new_note(
        ref, body_md="# Hello\n", kind="reflection", person="Ana", note_date="2026-10-18"
    )
    assert made["origin"] == "app" and made["kind"] == "reflection"
    assert made["created_via"] == "web"
    assert made["attachments"] == [] and made["links"] == []
    got = ok(ref.get(f"/notes/{made['id']}"), "Note")
    assert got["body_md"] == "# Hello\n" and got["person"] == "Ana"


def test_create_takes_created_via_from_the_client(ref: Ref) -> None:
    assert new_note(ref, created_via="mobile")["created_via"] == "mobile"
    assert new_note(ref, created_via="bogus")["created_via"] == "web"


def test_create_without_a_title_is_422(ref: Ref) -> None:
    assert ref.post("/notes", json={"body_md": "x"}).status_code == 422


def test_get_a_missing_note_is_404(ref: Ref) -> None:
    fails(ref.get("/notes/999"), 404, "not_found")


def test_notes_belong_to_their_user(ref: Ref) -> None:
    note = new_note(ref)
    fails(ref.get(f"/notes/{note['id']}", headers=BOB), 404, "not_found")
    fails(ref.patch(f"/notes/{note['id']}", headers=BOB, json={"title": "x"}), 404)
    fails(ref.delete(f"/notes/{note['id']}", headers=BOB), 404)
    assert ok(ref.get("/notes", headers=BOB), "NoteList")["items"] == []


def test_patch_changes_only_what_is_sent_and_null_clears(ref: Ref) -> None:
    note = new_note(ref, person="Ana", place="Hall")
    patched = ok(ref.patch(f"/notes/{note['id']}", json={"title": "New", "place": None}), "Note")
    assert patched["title"] == "New" and patched["place"] is None
    assert patched["person"] == "Ana"
    assert patched["version"] == note["version"] + 1


def test_patch_an_imported_note_body_is_409_read_only(ref: Ref) -> None:
    result = sync.upsert(ref.cfg, USER, upsert_body("d1"))
    fails(ref.patch(f"/notes/{result.note_id}", json={"body_md": "x"}), 409, "read_only_import")
    edited = ok(ref.patch(f"/notes/{result.note_id}", json={"kind": "lecture"}), "Note")
    assert edited["kind"] == "lecture"


def test_autosave_applies_then_reports_a_conflict(ref: Ref) -> None:
    note = new_note(ref, body_md="a")
    saved = ok(ref.patch(f"/notes/{note['id']}/autosave", json={"body_md": "b", "version": 1}))
    validate("AutosaveResult", saved)
    assert set(saved) == {"note"} and saved["note"]["body_md"] == "b"
    assert saved["note"]["version"] == 2
    stale = ok(ref.patch(f"/notes/{note['id']}/autosave", json={"body_md": "c", "version": 1}))
    validate("AutosaveResult", stale)
    assert set(stale) == {"conflict", "server_version", "server_data"}
    assert stale["conflict"] is True and stale["server_version"] == 2
    assert stale["server_data"]["body_md"] == "b"


def test_autosave_refuses_an_imported_note(ref: Ref) -> None:
    result = sync.upsert(ref.cfg, USER, upsert_body("d1"))
    fails(
        ref.patch(f"/notes/{result.note_id}/autosave", json={"body_md": "x", "version": 1}),
        409,
        "read_only_import",
    )


def test_delete_is_204_then_404(ref: Ref) -> None:
    note = new_note(ref)
    assert ref.delete(f"/notes/{note['id']}").status_code == 204
    fails(ref.get(f"/notes/{note['id']}"), 404)
    fails(ref.delete(f"/notes/{note['id']}"), 404)


# -- list -----------------------------------------------------------------------------------


def test_list_filters_and_pages(ref: Ref) -> None:
    for i in range(5):
        new_note(
            ref, f"Note {i}", note_date=f"2026-10-0{i + 1}", kind="lecture" if i % 2 else "note"
        )
    page = ok(ref.get("/notes", params={"limit": 2}), "NoteList")
    assert [n["title"] for n in page["items"]] == ["Note 4", "Note 3"]
    assert page["next_cursor"]
    nxt = ok(ref.get("/notes", params={"limit": 2, "before": page["next_cursor"]}), "NoteList")
    assert [n["title"] for n in nxt["items"]] == ["Note 2", "Note 1"]
    lectures = ok(ref.get("/notes", params={"kind": "lecture"}), "NoteList")
    assert {n["title"] for n in lectures["items"]} == {"Note 1", "Note 3"}
    ranged = ok(ref.get("/notes", params={"date_from": "2026-10-02", "date_to": "2026-10-03"}))
    assert {n["title"] for n in ranged["items"]} == {"Note 1", "Note 2"}
    assert [n["title"] for n in ok(ref.get("/notes", params={"q": "note 3"}))["items"]] == [
        "Note 3"
    ]


def test_list_limit_is_bounded_and_origin_is_an_enum(ref: Ref) -> None:
    assert ref.get("/notes", params={"limit": 0}).status_code == 422
    assert ref.get("/notes", params={"limit": 101}).status_code == 422
    assert ref.get("/notes", params={"origin": "elsewhere"}).status_code == 422


def test_list_a_bad_cursor_is_422(ref: Ref) -> None:
    fails(ref.get("/notes", params={"before": "!!"}), 422, "invalid_cursor")


def test_list_origin_filter_and_sync_sources(ref: Ref) -> None:
    new_note(ref, "Mine")
    sync.upsert(ref.cfg, USER, upsert_body("d1", source_workspace="Dave2025"))
    sync.upsert(ref.cfg, USER, upsert_body("d2", source_workspace="Dave2025"))
    page = ok(ref.get("/notes"), "NoteList")
    assert [s["note_count"] for s in page["sync_sources"]] == [2]
    assert page["sync_sources"][0]["source_workspace"] == "Dave2025"
    assert page["sync_sources"][0]["source_system"] == "obsidian"
    assert [n["title"] for n in ok(ref.get("/notes", params={"origin": "app"}))["items"]] == [
        "Mine"
    ]
    assert len(ok(ref.get("/notes", params={"origin": "source"}))["items"]) == 2


def test_list_hides_deleted_notes_unless_asked(ref: Ref) -> None:
    kept = sync.upsert(ref.cfg, USER, upsert_body("keep"))
    gone = sync.upsert(ref.cfg, USER, upsert_body("gone"))
    sync.tombstone(ref.cfg, USER, "obsidian", "Vault", ["gone"])
    plain = ok(ref.get("/notes"))
    assert [n["id"] for n in plain["items"]] == [kept.note_id]
    shown = ok(ref.get("/notes", params={"include_deleted": "true"}), "NoteList")
    assert {n["id"] for n in shown["items"]} == {kept.note_id, gone.note_id}
    deleted = next(n for n in shown["items"] if n["id"] == gone.note_id)
    assert deleted["deleted_at"]


def test_list_summaries_carry_the_k2_fields(ref: Ref) -> None:
    note_id = add_note(
        ref.db,
        title="Class",
        origin="source",
        source_system="obsidian",
        source_workspace="Dave2025",
        source_path="One on one/class.md",
        frontmatter='{"duration": "25"}',
        note_date="2026-10-18",
        review_pending=3,
    )
    add_link(ref.db, note_id, "composer", 1)
    add_link(ref.db, note_id, "repertoire", 10, action_item="slow down")
    add_link(ref.db, note_id, "movement", 103)
    item = ok(ref.get("/notes"), "NoteList")["items"][0]
    assert item["source_workspace"] == "Dave2025" and item["source_path"] == "One on one/class.md"
    assert item["duration_min"] == 25 and item["review_pending"] == 3
    assert item["action_count"] == 1 and item["link_count"] == 3
    # works before movements before composers
    assert [x["entity_type"] for x in item["top_links"]] == ["repertoire", "movement", "composer"]
    assert item["top_links"][0]["entity_label"] == "Études, Op.10"


def test_list_include_hygiene_adds_the_block_only_when_asked(ref: Ref) -> None:
    new_note(ref)
    assert "hygiene" not in ok(ref.get("/notes"))
    asked = ok(ref.get("/notes", params={"include_hygiene": "true"}), "NoteList")
    assert asked["hygiene"]["total"] == 0 and asked["hygiene"]["truncated"] is False
    off = ref.with_policy(hygiene=False)
    assert "hygiene" not in ok(off.get("/notes", params={"include_hygiene": "true"}))


def test_get_note_include_hygiene_flags_a_tombstone(ref: Ref) -> None:
    result = sync.upsert(ref.cfg, USER, upsert_body("d1"))
    sync.tombstone(ref.cfg, USER, "obsidian", "Vault", ["d1"])
    plain = ok(ref.get(f"/notes/{result.note_id}"))
    assert "hygiene" not in plain
    asked = ok(ref.get(f"/notes/{result.note_id}", params={"include_hygiene": "true"}), "Note")
    assert [i["kind"] for i in asked["hygiene"]["issues"]] == ["tombstoned_note"]


# -- by-entity ------------------------------------------------------------------------------


def test_by_entity_lists_notes_with_their_links(ref: Ref) -> None:
    a = add_note(ref.db, title="A")
    b = add_note(ref.db, title="B")
    add_link(ref.db, a, "repertoire", 10, quote="q")
    add_link(ref.db, b, "movement", 103)
    found = ok(ref.get("/notes/by-entity/repertoire/10"), "EntityNotes")
    assert [row["note"]["title"] for row in found["items"]] == ["A"]
    link = found["items"][0]["links"][0]
    assert link["entity_label"] == "Études, Op.10" and link["quote"] == "q"
    assert "via" not in link or link["via"] is None


def test_by_entity_include_children_follows_the_scheme(ref: Ref) -> None:
    a = add_note(ref.db, title="Piece note")
    b = add_note(ref.db, title="Movement note")
    add_link(ref.db, a, "repertoire", 10)
    add_link(ref.db, b, "movement", 103)
    plain = ok(ref.get("/notes/by-entity/repertoire/10"))
    assert [r["note"]["title"] for r in plain["items"]] == ["Piece note"]
    deep = ok(ref.get("/notes/by-entity/repertoire/10", params={"include_children": "true"}))
    validate("EntityNotes", deep)
    assert {r["note"]["title"] for r in deep["items"]} == {"Piece note", "Movement note"}
    via = next(r for r in deep["items"] if r["note"]["title"] == "Movement note")["links"][0]["via"]
    assert via == {"entity_type": "movement", "entity_id": 103}
    composer = ok(ref.get("/notes/by-entity/composer/1", params={"include_children": "true"}))
    assert {r["note"]["title"] for r in composer["items"]} == {"Piece note", "Movement note"}


def test_by_entity_limit_is_bounded(ref: Ref) -> None:
    assert ref.get("/notes/by-entity/repertoire/10", params={"limit": 0}).status_code == 422
    assert ref.get("/notes/by-entity/repertoire/ten").status_code == 422


# -- signed URLs ----------------------------------------------------------------------------


def test_responses_embed_mounted_signed_urls(ref: Ref) -> None:
    blob_id, digest = add_blob(ref.db)
    sync.upsert(
        ref.cfg,
        USER,
        upsert_body("d1", attachments=[attachment_ref(digest, "![[a.webp]]", "a.webp")]),
    )
    item = ok(ref.get("/notes"), "NoteList")["items"][0]
    assert item["thumbnail_url"].startswith(f"{ORIGIN}{API}/attachments/{blob_id}/content?exp=")
    assert "thumbnail_blob_id" not in item
    note = ok(ref.get(f"/notes/{item['id']}"), "Note")
    url = note["attachments"][0]["content_url"]
    assert url.startswith(f"{ORIGIN}{API}/attachments/{blob_id}/content?exp=") and "&sig=" in url
    assert note["attachments"][0]["blob_id"] == blob_id


def test_urls_follow_the_prefix_the_routers_were_built_with(ref: Ref) -> None:
    from app_ref import make_app
    from fastapi.testclient import TestClient

    blob_id, digest = add_blob(ref.db)
    sync.upsert(
        ref.cfg, USER, upsert_body("d1", attachments=[attachment_ref(digest, "![[a.webp]]")])
    )
    client = TestClient(make_app(ref.cfg, "/notes-api"))
    page = client.get("/notes-api/notes", headers=ALICE).json()
    assert page["items"][0]["thumbnail_url"].startswith(
        f"{ORIGIN}/notes-api/attachments/{blob_id}/content"
    )
    bare = TestClient(make_app(ref.cfg, ""))
    note_id = page["items"][0]["id"]
    got = bare.get(f"/notes/{note_id}", headers=ALICE).json()
    assert got["attachments"][0]["content_url"].startswith(
        f"{ORIGIN}/attachments/{blob_id}/content"
    )


def test_urls_name_the_host_the_request_came_to(ref: Ref) -> None:
    from app_ref import make_app
    from fastapi.testclient import TestClient

    blob_id, digest = add_blob(ref.db)
    sync.upsert(
        ref.cfg, USER, upsert_body("d1", attachments=[attachment_ref(digest, "![[a.webp]]")])
    )
    client = TestClient(make_app(ref.cfg), base_url="https://notes.example.test")
    thumb = client.get(f"{API}/notes", headers=ALICE).json()["items"][0]["thumbnail_url"]
    assert thumb.startswith(f"https://notes.example.test{API}/attachments/{blob_id}/content?exp=")


def test_a_public_base_url_overrides_the_request_origin(ref: Ref) -> None:
    from app_ref import make_app
    from fastapi.testclient import TestClient

    blob_id, digest = add_blob(ref.db)
    sync.upsert(
        ref.cfg, USER, upsert_body("d1", attachments=[attachment_ref(digest, "![[a.webp]]")])
    )
    client = TestClient(make_app(ref.cfg, API, "https://pt.example.com/"))
    page = client.get(f"{API}/notes", headers=ALICE).json()
    expected = f"https://pt.example.com{API}/attachments/{blob_id}/content?exp="
    assert page["items"][0]["thumbnail_url"].startswith(expected)


def test_frontmatter_is_never_rewritten(ref: Ref) -> None:
    sync.upsert(
        ref.cfg,
        USER,
        upsert_body("d1", frontmatter={"content_url": "/attachments/9/content", "n": {"a": 1}}),
    )
    item = ok(ref.get("/notes"))["items"][0]
    note = ok(ref.get(f"/notes/{item['id']}"))
    assert note["frontmatter"] == {"content_url": "/attachments/9/content", "n": {"a": 1}}
