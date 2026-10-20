"""REST: propose and confirm (C3, ga-mxal.10)."""

from __future__ import annotations

from typing import Any

from app_ref import BOB, Ref, fails, ok, validate

BODY = "# Etudes\n\nWork on Op. 10 nº 3 today.\n\nChopin wrote it for the left hand.\n"


def app_note(ref: Ref, body: str = BODY) -> int:
    """An app-authored note: nothing proposes it until the test asks."""
    return ok(ref.post("/notes", json={"title": "Class", "body_md": body}), "Note", 201)["id"]


def propose(ref: Ref, note_id: int, **params: Any) -> dict[str, Any]:
    return ok(ref.post(f"/notes/{note_id}/propose", params=params), "Proposal")


# -- propose --------------------------------------------------------------------------------


def test_propose_computes_then_serves_the_cache(ref: Ref) -> None:
    note_id = app_note(ref)
    first = propose(ref, note_id)
    assert first["note_id"] == note_id and first["generated_by"] == ["resolver"]
    assert first["cached"] is False
    labels = {(link["entity_type"], link["entity_id"]) for link in first["links"]}
    assert ("movement", 103) in labels
    for link in first["links"]:
        assert link["entity_label"] and 0 <= link["confidence"] <= 1
    again = propose(ref, note_id)
    assert again["cached"] is True and again["proposed_at"]
    assert {(link["entity_type"], link["entity_id"]) for link in again["links"]} == labels


def test_propose_refresh_recomputes(ref: Ref) -> None:
    note_id = app_note(ref)
    propose(ref, note_id)
    fresh = propose(ref, note_id, refresh="true")
    assert fresh["cached"] is False


def test_propose_updates_the_review_count(ref: Ref) -> None:
    note_id = app_note(ref)
    assert ok(ref.get(f"/notes/{note_id}"))["review_pending"] == 0
    proposal = propose(ref, note_id)
    expected = len(proposal["links"]) + len(proposal["unresolved"]) + len(proposal["action_items"])
    assert expected > 0
    assert ok(ref.get(f"/notes/{note_id}"))["review_pending"] == expected
    listed = ok(ref.get("/notes"))["items"][0]
    assert listed["review_pending"] == expected


def test_propose_llm_is_503_unless_the_host_enabled_it(ref: Ref) -> None:
    note_id = app_note(ref)
    fails(ref.post(f"/notes/{note_id}/propose", params={"llm": "true"}), 503, "llm_disabled")
    # on in the policy but the host injected no provider call: still disabled, never a 500
    on = ref.with_policy(llm_enrich=True)
    fails(on.post(f"/notes/{note_id}/propose", params={"llm": "true"}), 503, "llm_disabled")


def test_propose_a_missing_note_is_404(ref: Ref) -> None:
    fails(ref.post("/notes/999/propose"), 404, "not_found")
    note_id = app_note(ref)
    fails(ref.post(f"/notes/{note_id}/propose", headers=BOB), 404, "not_found")


def test_propose_include_hygiene(ref: Ref) -> None:
    note_id = app_note(ref)
    assert "hygiene" not in propose(ref, note_id)
    asked = ok(ref.post(f"/notes/{note_id}/propose", params={"include_hygiene": "true"}))
    assert "total" in asked["hygiene"]


# -- confirm --------------------------------------------------------------------------------


def test_confirm_creates_links_backlog_and_the_k10_event(ref: Ref) -> None:
    note_id = app_note(ref)
    body = {
        "links": [
            {
                "entity_type": "movement",
                "entity_id": 103,
                "anchor": "etudes",
                "quote": "Op. 10 nº 3",
                "proposed_by": "resolver",
                "confidence": 0.92,
            },
            {"entity_type": "composer", "entity_id": 1},
        ],
        "rejected": [{"entity_type": "technique", "entity_id": 7}],
        "action_items": [
            {"text": "slow, hands apart", "lane": "practice", "link_index": 0},
        ],
        "takeaways": [{"anchor": "etudes", "comment": "Keep the wrist loose"}],
    }
    result = ok(ref.post(f"/notes/{note_id}/confirm", json=body), "ConfirmResult")
    assert result["links_created"] == 2 and result["links_rejected"] == 1
    assert result["backlog_created"] == [100] and result["takeaways_created"] == 1
    assert result["someday_created"] == 0 and result["review_pending"] == 0

    note = ok(ref.get(f"/notes/{note_id}"), "Note")
    by_entity = {(link["entity_type"], link["entity_id"]): link for link in note["links"]}
    assert set(by_entity) == {("movement", 103), ("composer", 1)}
    moved = by_entity[("movement", 103)]
    assert moved["action_item"] == "slow, hands apart" and moved["backlog_id"] == 100
    assert moved["comment"] == "Keep the wrist loose" and moved["entity_label"] == "Op.10 nº 3"

    assert ref.hooks.names() == ["note_created", "note_enriched"]
    _, _, entity, _ = ref.hooks.events[-1]
    assert entity["entity_type"] == "note" and entity["entity_id"] == note_id
    assert (entity["links_created"], entity["backlog_created"], entity["rejected"]) == (2, 1, 1)
    assert entity["deferred"] == 0
    assert ref.hooks.actions[0][2] == "practice"


def test_confirm_is_idempotent_and_counts_only_changes(ref: Ref) -> None:
    note_id = app_note(ref)
    body = {"links": [{"entity_type": "composer", "entity_id": 1}]}
    assert ok(ref.post(f"/notes/{note_id}/confirm", json=body))["links_created"] == 1
    assert ok(ref.post(f"/notes/{note_id}/confirm", json=body))["links_created"] == 0
    assert len(ok(ref.get(f"/notes/{note_id}"))["links"]) == 1


def test_confirm_a_rejection_suppresses_the_next_proposal(ref: Ref) -> None:
    note_id = app_note(ref)
    first = propose(ref, note_id)
    link = next(x for x in first["links"] if x["entity_id"] == 103)
    ok(
        ref.post(
            f"/notes/{note_id}/confirm",
            json={
                "rejected": [
                    {"entity_type": "movement", "entity_id": 103, "anchor": link["anchor"]}
                ]
            },
        )
    )
    after = propose(ref, note_id, refresh="true")
    assert ("movement", 103) not in {(x["entity_type"], x["entity_id"]) for x in after["links"]}


def test_confirm_deferred_items_stay_pending(ref: Ref) -> None:
    note_id = app_note(ref)
    propose(ref, note_id)
    body = {
        "links": [{"entity_type": "composer", "entity_id": 1}],
        "deferred": [{"mention": "Debussy pick", "anchor": None}],
    }
    result = ok(ref.post(f"/notes/{note_id}/confirm", json=body), "ConfirmResult")
    assert result["review_pending"] == 1
    assert ok(ref.get(f"/notes/{note_id}"))["review_pending"] == 1
    _, _, entity, _ = ref.hooks.events[-1]
    assert entity["deferred"] == 1


def test_confirm_a_takeaway_without_a_link_is_422(ref: Ref) -> None:
    note_id = app_note(ref)
    body = {"takeaways": [{"anchor": "etudes", "comment": "No link here"}]}
    fails(ref.post(f"/notes/{note_id}/confirm", json=body), 422, "takeaway_needs_link")
    assert ok(ref.get(f"/notes/{note_id}"))["links"] == []


def test_confirm_an_action_without_a_target_is_422(ref: Ref) -> None:
    note_id = app_note(ref)
    body = {"action_items": [{"text": "do it", "lane": "practice"}]}
    fails(ref.post(f"/notes/{note_id}/confirm", json=body), 422, "action_needs_link")
    bad = {"links": [], "action_items": [{"text": "x", "lane": "practice", "link_index": 4}]}
    fails(ref.post(f"/notes/{note_id}/confirm", json=bad), 422, "invalid_link_index")


def test_confirm_someday_is_422_unless_the_host_keeps_them(ref: Ref) -> None:
    note_id = app_note(ref)
    body = {
        "someday": [{"mention": "Fauré nocturne", "kind_hint": "work", "composer_label": "Fauré"}]
    }
    fails(ref.post(f"/notes/{note_id}/confirm", json=body), 422, "someday_unsupported")
    ref.hooks.enable_someday()
    keeps = ref.with_policy(someday=True)
    result = ok(keeps.post(f"/notes/{note_id}/confirm", json=body), "ConfirmResult")
    assert result["someday_created"] == 1
    assert ref.hooks.someday[0][2]["mention"] == "Fauré nocturne"


def test_confirm_validates_the_body_and_the_owner(ref: Ref) -> None:
    note_id = app_note(ref)
    assert (
        ref.post(f"/notes/{note_id}/confirm", json={"links": [{"entity_id": 1}]}).status_code == 422
    )
    fails(ref.post("/notes/999/confirm", json={}), 404, "not_found")
    fails(ref.post(f"/notes/{note_id}/confirm", json={}, headers=BOB), 404, "not_found")
    validate("ConfirmBody", {"links": [], "rejected": []})
