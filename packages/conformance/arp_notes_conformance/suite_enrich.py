"""Conformance: propose, confirm, rejection, deferred (A.2, K§2, K§3).

Owner: C7b ga-mxal.38. The resolver behind a host is the host's own (PT's picker, the reference
app's toy scheme), so the kit never asks it for a particular answer: proposal *shapes* must
validate even when empty. The checks that need a real proposal use the fixture's
`recognised_document` and are skipped, with the reason, when the host proposes nothing for it.

What is proved: propose is cached and `refresh` recomputes (K§2); confirm persists links; a
rejection persists as `status='rejected'` and keeps its `(entity, anchor)` out of every later
proposal, as does a confirmed link (ADR diff rule, K§3.5); deferred items are what
`review_pending` counts after a confirm (K§3.3) and a confirm without any leaves none.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .harness import UNKNOWN_ID, CheckSkipped, Harness
from .suite_core import link_target, need, same

Check = Callable[[Harness], None]
CHECKS: list[tuple[str, Check]] = []


def check(name: str) -> Callable[[Check], Check]:
    def register(fn: Check) -> Check:
        CHECKS.append((name, fn))
        return fn

    return register


def propose(h: Harness, note_id: int, **params: Any) -> dict[str, Any]:
    flags = {k: ("true" if v is True else v) for k, v in params.items() if v is not False}
    return h.call("POST", f"/notes/{note_id}/propose", shape="Proposal", params=flags or None)


def key(link: dict[str, Any]) -> tuple[str, int, str | None]:
    return (link["entity_type"], link["entity_id"], link.get("anchor"))


def confirm(h: Harness, note_id: int, body: dict[str, Any]) -> dict[str, Any]:
    full = {"links": [], "rejected": [], "action_items": [], **body}
    return h.call("POST", f"/notes/{note_id}/confirm", shape="ConfirmResult", json=full)


def recognised(h: Harness) -> tuple[int, dict[str, Any]]:
    """Upsert the recognised document and propose from it; skip when nothing comes back."""
    if h.fixture.recognised_document is None:
        raise CheckSkipped("the fixture names no recognised_document the host proposes from")
    note_id, _ = h.upsert(h.fixture.doc(h.fixture.recognised_document))
    proposal = propose(h, note_id, refresh=True)
    singles = [link for link in proposal["links"] if not link.get("candidates")]
    if not singles:
        raise CheckSkipped("the host proposed no unambiguous link for the recognised document")
    return note_id, proposal


# -- propose --------------------------------------------------------------------------------


@check("enrich.propose_shapes")
def propose_shapes(h: Harness) -> None:
    doc = h.fixture.doc("masterclass")
    note_id, _ = h.upsert(doc)
    first = propose(h, note_id)
    same(first["note_id"], note_id, "Proposal.note_id")
    need(
        "resolver" in first["generated_by"],
        f"generated_by {first['generated_by']} lacks 'resolver'",
    )
    for name in ("links", "action_items", "takeaways", "unresolved"):
        need(isinstance(first[name], list), f"Proposal.{name} must be a list (empty is fine)")

    cached = propose(h, note_id)
    same(cached.get("cached"), True, "a second propose answers from the cache (K§2)")
    same(
        [key(link) for link in cached["links"]],
        [key(link) for link in first["links"]],
        "links of the cached proposal",
    )
    fresh = propose(h, note_id, refresh=True)
    need(not fresh.get("cached"), "propose?refresh=true must recompute, not answer from the cache")

    app_note = h.create_note("Proposed", body_md="Plain text with nothing to link.\n")
    plain = propose(h, app_note["id"])
    same(plain["note_id"], app_note["id"], "Proposal.note_id of an app note")

    h.fails("POST", f"/notes/{UNKNOWN_ID}/propose", 404, "not_found")
    if not h.capabilities["llm_enrich"]:
        h.fails("POST", f"/notes/{note_id}/propose", 503, "llm_disabled", params={"llm": "true"})


@check("enrich.proposed_links_are_well_formed")
def proposed_links_are_well_formed(h: Harness) -> None:
    _, proposal = recognised(h)
    for link in proposal["links"]:
        need(0 <= link["confidence"] <= 1, f"confidence {link['confidence']} is outside 0..1")
        need(bool(link["entity_label"]), f"{key(link)} has no entity_label")
        need(bool(link["quote"]), f"{key(link)} has no quote")
        for cand in link.get("candidates") or []:
            need(0 <= cand["confidence"] <= 1, f"candidate confidence {cand['confidence']}")
    known = {t for s in h.capabilities["schemes"] for t in s["entity_types"]}
    for link in proposal["links"]:
        need(
            link["entity_type"] in known,
            f"proposed entity_type {link['entity_type']!r} is not in capabilities.schemes "
            f"{sorted(known)}",
        )


# -- confirm --------------------------------------------------------------------------------


@check("enrich.confirm_creates_links")
def confirm_creates_links(h: Harness) -> None:
    target = link_target(h)
    doc = h.fixture.doc("masterclass")
    note_id, _ = h.upsert(doc)
    entity = {"entity_type": target.entity_type, "entity_id": target.entity_id}
    result = confirm(
        h,
        note_id,
        {
            "links": [
                {**entity, "quote": "whole note", "comment": "kept", "proposed_by": "resolver"},
                {**entity, "anchor": next(iter(doc.anchors.values()), None), "quote": "a part"},
            ],
        },
    )
    same(result["links_created"], 2, "links_created")
    same(result["links_rejected"], 0, "links_rejected")
    note = h.get_note(note_id)
    same(len(note["links"]), 2, "links on the note after confirm")
    same({link["status"] for link in note["links"]}, {"confirmed"}, "status of confirmed links")
    for link in note["links"]:
        same((link["entity_type"], link["entity_id"]), tuple(entity.values()), "link entity")
        need(bool(link["entity_label"]), "a confirmed link carries entity_label")
    same(sorted(link["quote"] for link in note["links"]), ["a part", "whole note"], "link quotes")
    listed = next(
        i for i in h.list_notes(q=h.tag, origin="source", limit=100)["items"] if i["id"] == note_id
    )
    same(listed["link_count"], 2, "link_count on the list row")

    h.fails(
        "POST",
        f"/notes/{UNKNOWN_ID}/confirm",
        404,
        "not_found",
        json={"links": [], "rejected": [], "action_items": []},
    )


@check("enrich.confirm_with_action_item")
def confirm_with_action_item(h: Harness) -> None:
    target = link_target(h)
    note_id, _ = h.upsert(h.fixture.doc("masterclass"))
    entity = {"entity_type": target.entity_type, "entity_id": target.entity_id}
    result = confirm(
        h,
        note_id,
        {
            "links": [{**entity, "quote": "pedalling"}],
            "action_items": [
                {"text": "Record the pedal changes", "lane": "practice", "link_index": 0}
            ],
        },
    )
    need(isinstance(result["backlog_created"], list), "backlog_created must be a list")
    links = h.get_note(note_id)["links"]
    same(
        [link["action_item"] for link in links],
        ["Record the pedal changes"],
        "action_item stored on the link it was attached to",
    )
    h.fails(
        "POST",
        f"/notes/{note_id}/confirm",
        422,
        json={
            "links": [],
            "rejected": [],
            "action_items": [{"text": "no link to hang on", "lane": "practice", "link_index": 7}],
        },
    )


# -- rejection and the diff rule ------------------------------------------------------------


@check("enrich.rejection_persists_and_suppresses")
def rejection_persists_and_suppresses(h: Harness) -> None:
    note_id, proposal = recognised(h)
    victim = next(link for link in proposal["links"] if not link.get("candidates"))
    gone = key(victim)
    result = confirm(
        h,
        note_id,
        {"rejected": [{"entity_type": gone[0], "entity_id": gone[1], "anchor": gone[2]}]},
    )
    same(result["links_rejected"], 1, "links_rejected")
    need(
        all(key(link) != gone for link in h.get_note(note_id)["links"]),
        f"{gone} was rejected but the note still lists it among its links",
    )

    again = propose(h, note_id, refresh=True)
    need(
        gone not in [key(link) for link in again["links"]],
        f"{gone} was rejected and is proposed again by a refreshed propose",
    )
    cached = propose(h, note_id)
    need(
        gone not in [key(link) for link in cached["links"]],
        f"{gone} was rejected and is still in the cached proposal",
    )
    doc = h.fixture.doc(h.fixture.recognised_document or "masterclass")
    h.upsert(doc, body=doc.body + "\nA line added after the rejection.\n")
    after_edit = propose(h, note_id, refresh=True)
    need(
        gone not in [key(link) for link in after_edit["links"]],
        f"{gone} was rejected and came back after the note body changed",
    )
    need(
        all(key(link) != gone for link in h.get_note(note_id)["links"]),
        f"{gone} was rejected and a re-sync with a changed body made it a link",
    )


@check("enrich.confirmed_is_not_reproposed")
def confirmed_is_not_reproposed(h: Harness) -> None:
    note_id, proposal = recognised(h)
    chosen = next(link for link in proposal["links"] if not link.get("candidates"))
    gone = key(chosen)
    result = confirm(
        h,
        note_id,
        {
            "links": [
                {
                    "entity_type": gone[0],
                    "entity_id": gone[1],
                    "anchor": gone[2],
                    "quote": chosen["quote"],
                }
            ]
        },
    )
    same(result["links_created"], 1, "links_created")
    again = propose(h, note_id, refresh=True)
    need(
        gone not in [key(link) for link in again["links"]],
        f"{gone} is already confirmed and is proposed again",
    )


# -- deferred -------------------------------------------------------------------------------


@check("enrich.deferred_keeps_review_pending")
def deferred_keeps_review_pending(h: Harness) -> None:
    doc = h.fixture.doc(h.fixture.recognised_document or "masterclass")
    note_id, _ = h.upsert(doc)
    propose(h, note_id)

    later = [
        {"mention": f"Debussy pick {h.tag}", "anchor": None},
        {"mention": f"Bach pick {h.tag}", "anchor": None},
    ]
    result = confirm(h, note_id, {"deferred": later})
    same(result["review_pending"], 2, "ConfirmResult.review_pending after deferring two items")
    same(h.get_note(note_id)["review_pending"], 2, "Note.review_pending after deferring two")
    row = next(
        i for i in h.list_notes(q=h.tag, origin="source", limit=100)["items"] if i["id"] == note_id
    )
    same(row["review_pending"], 2, "NoteSummary.review_pending after deferring two")

    again = confirm(h, note_id, {"deferred": later[:1]})
    same(again["review_pending"], 1, "review_pending after deferring one of them again")

    done = confirm(h, note_id, {})
    same(done["review_pending"], 0, "review_pending after a confirm that defers nothing")
    same(h.get_note(note_id)["review_pending"], 0, "Note.review_pending once nothing is deferred")
