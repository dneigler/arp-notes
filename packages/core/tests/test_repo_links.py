"""repo: confirm_links and by_entity (C1b, ga-mxal.8; contract A.2, K§2, K§10)."""

from __future__ import annotations

from typing import Any

import pytest
from arp_notes import repo
from arp_notes.config import HostConfig
from arp_notes.models import ConfirmBody
from arp_notes.testing.fakedb import FakeDb
from repo_support import (
    OTHER,
    USER,
    FakeHooks,
    FakeScheme,
    add_link,
    add_note,
    make_cfg,
)

pytestmark = pytest.mark.usefixtures("signed_urls")


def confirm(cfg: HostConfig, note_id: int, **body: Any) -> Any:
    return repo.confirm_links(cfg, USER, note_id, ConfirmBody.model_validate(body))


def link_rows(db: FakeDb, note_id: int) -> list[dict[str, Any]]:
    return db.run("SELECT * FROM note_links WHERE note_id = %s ORDER BY id", [note_id])


ETUDE = {"entity_type": "repertoire", "entity_id": 35, "anchor": "etude-3"}


# --- links ------------------------------------------------------------------------------------


def test_confirm_stores_links_with_their_provenance(
    notes_cfg: HostConfig, notes_db: FakeDb
) -> None:
    note_id = add_note(notes_db)
    result = confirm(
        notes_cfg,
        note_id,
        links=[
            {
                **ETUDE,
                "quote": "operatic",
                "comment": "sing it",
                "proposed_by": "resolver",
                "confidence": 0.9,
            },
            {"entity_type": "composer", "entity_id": 1},
        ],
    )
    assert result.model_dump() == {
        "links_created": 2,
        "links_rejected": 0,
        "backlog_created": [],
        "takeaways_created": 0,
        "someday_created": 0,
        "review_pending": 0,
    }
    first, second = link_rows(notes_db, note_id)
    assert (first["status"], first["anchor"], first["quote"], first["comment"]) == (
        "confirmed",
        "etude-3",
        "operatic",
        "sing it",
    )
    assert (first["proposed_by"], round(first["confidence"], 2), first["user_id"]) == (
        "resolver",
        0.9,
        USER,
    )
    assert (second["anchor"], second["proposed_by"], second["sort_order"]) == (None, "user", 1)


def test_reconfirming_updates_and_never_duplicates(notes_cfg: HostConfig, notes_db: FakeDb) -> None:
    note_id = add_note(notes_db)
    body = {"links": [{**ETUDE, "quote": "q1", "confidence": 0.7}]}
    assert confirm(notes_cfg, note_id, **body).links_created == 1
    before = link_rows(notes_db, note_id)

    again = confirm(notes_cfg, note_id, **body)
    assert (again.links_created, again.links_rejected) == (0, 0)
    assert link_rows(notes_db, note_id) == [
        {**before[0], "updated_at": link_rows(notes_db, note_id)[0]["updated_at"]}
    ]

    # New values win; omitted ones keep the old value.
    confirm(notes_cfg, note_id, links=[{**ETUDE, "quote": "q2", "comment": "c"}])
    [row] = link_rows(notes_db, note_id)
    assert (row["quote"], row["comment"], round(row["confidence"], 2)) == ("q2", "c", 0.7)
    # A different anchor, or no anchor, is a different link.
    confirm(notes_cfg, note_id, links=[{**ETUDE, "anchor": "other"}, {**ETUDE, "anchor": None}])
    assert len(link_rows(notes_db, note_id)) == 3


def test_rejections_persist_and_are_idempotent(notes_cfg: HostConfig, notes_db: FakeDb) -> None:
    note_id = add_note(notes_db)
    rej = {"rejected": [{"entity_type": "composer", "entity_id": 1, "anchor": "intro"}]}
    assert confirm(notes_cfg, note_id, **rej).links_rejected == 1
    assert confirm(notes_cfg, note_id, **rej).links_rejected == 0
    [row] = link_rows(notes_db, note_id)
    assert (row["status"], row["anchor"]) == ("rejected", "intro")
    # Rejected links are not content.
    assert repo.get_note(notes_cfg, USER, note_id).links == []
    assert repo.list_notes(notes_cfg, USER).items[0].link_count == 0


def test_a_decision_can_change(notes_cfg: HostConfig, notes_db: FakeDb) -> None:
    note_id = add_note(notes_db)
    confirm(notes_cfg, note_id, links=[ETUDE])
    flipped = confirm(notes_cfg, note_id, rejected=[ETUDE])
    assert flipped.links_rejected == 1
    assert [r["status"] for r in link_rows(notes_db, note_id)] == ["rejected"]
    back = confirm(notes_cfg, note_id, links=[ETUDE])
    assert back.links_created == 1
    assert [r["status"] for r in link_rows(notes_db, note_id)] == ["confirmed"]
    # Both in one request: the confirmation wins.
    other = {"entity_type": "composer", "entity_id": 1}
    confirm(notes_cfg, note_id, links=[other], rejected=[other])
    assert [r["status"] for r in link_rows(notes_db, note_id)] == ["confirmed", "confirmed"]


def test_confirm_404s_for_a_missing_or_foreign_note(
    notes_cfg: HostConfig, notes_db: FakeDb
) -> None:
    theirs = add_note(notes_db, OTHER)
    for note_id in (theirs, 9999):
        with pytest.raises(repo.NoteNotFound):
            confirm(notes_cfg, note_id, links=[ETUDE])
    assert link_rows(notes_db, theirs) == []


def test_confirm_reports_the_stored_review_pending(notes_cfg: HostConfig, notes_db: FakeDb) -> None:
    note_id = add_note(notes_db, review_pending=4)
    assert confirm(notes_cfg, note_id, links=[ETUDE]).review_pending == 4


# --- takeaways --------------------------------------------------------------------------------


def test_takeaways_become_a_comment_on_the_link_at_their_anchor(
    notes_cfg: HostConfig, notes_db: FakeDb
) -> None:
    note_id = add_note(notes_db)
    add_link(notes_db, note_id, "repertoire", 35, anchor="etude-3", sort_order=0)
    add_link(notes_db, note_id, "composer", 1, anchor="etude-3", sort_order=1)
    add_link(notes_db, note_id, "repertoire", 35, anchor="etude-4", sort_order=2)
    body = {"takeaways": [{"anchor": "etude-3", "comment": "operatic"}]}

    assert confirm(notes_cfg, note_id, **body).takeaways_created == 1
    comments = [r["comment"] for r in link_rows(notes_db, note_id)]
    assert comments == ["operatic", None, None]  # the first confirmed link at that anchor
    # A repeat adds nothing; a second, different takeaway is appended as a paragraph.
    assert confirm(notes_cfg, note_id, **body).takeaways_created == 0
    confirm(notes_cfg, note_id, takeaways=[{"anchor": "etude-3", "comment": "drop the hand"}])
    assert link_rows(notes_db, note_id)[0]["comment"] == "operatic\n\ndrop the hand"


def test_a_takeaway_can_use_a_link_confirmed_in_the_same_request(
    notes_cfg: HostConfig, notes_db: FakeDb
) -> None:
    note_id = add_note(notes_db)
    confirm(notes_cfg, note_id, links=[ETUDE], takeaways=[{"anchor": "etude-3", "comment": "t"}])
    assert link_rows(notes_db, note_id)[0]["comment"] == "t"


def test_a_takeaway_without_a_link_is_422_and_writes_nothing(
    notes_cfg: HostConfig, notes_db: FakeDb, fake_hooks: FakeHooks
) -> None:
    note_id = add_note(notes_db)
    with pytest.raises(repo.TakeawayNeedsLink) as err:
        confirm(
            notes_cfg,
            note_id,
            links=[ETUDE],  # confirmed in the same request, but at another anchor
            takeaways=[{"anchor": "elsewhere", "comment": "t"}],
            action_items=[{"text": "practise", "link_index": 0, "lane": "practice"}],
        )
    assert (err.value.status, err.value.body["error"]) == (422, "takeaway_needs_link")
    assert link_rows(notes_db, note_id) == []  # the whole confirm rolled back
    assert fake_hooks.actions == [] and fake_hooks.events == []


# --- action items -----------------------------------------------------------------------------


def test_action_items_go_through_the_hook_and_land_on_the_link(
    notes_cfg: HostConfig, notes_db: FakeDb, fake_hooks: FakeHooks
) -> None:
    note_id = add_note(notes_db, title="Howat")
    result = confirm(
        notes_cfg,
        note_id,
        links=[{"entity_type": "composer", "entity_id": 1}, ETUDE],
        action_items=[{"text": "practise Nº 12 slowly", "link_index": 1, "lane": "practice"}],
    )
    assert result.backlog_created == [100]
    composer, etude = link_rows(notes_db, note_id)
    assert (etude["action_item"], etude["backlog_id"]) == ("practise Nº 12 slowly", 100)
    assert (composer["action_item"], composer["backlog_id"]) == (None, None)

    [(user, link, lane)] = fake_hooks.actions
    assert (user, lane) == (USER, "practice")
    assert (link["id"], link["note_id"], link["entity_type"], link["entity_id"]) == (
        etude["id"],
        note_id,
        "repertoire",
        35,
    )
    assert (link["anchor"], link["action_item"], link["note_title"]) == (
        "etude-3",
        "practise Nº 12 slowly",
        "Howat",
    )
    assert repo.list_notes(notes_cfg, USER).items[0].action_count == 1


def test_confirm_stores_the_lane_and_reads_it_back(
    notes_cfg: HostConfig, notes_db: FakeDb, fake_hooks: FakeHooks
) -> None:
    """K§13.3: the lane is written next to backlog_id and comes back on get_note and by_entity."""
    note_id = add_note(notes_db)
    confirm(
        notes_cfg,
        note_id,
        links=[{"entity_type": "composer", "entity_id": 1}, ETUDE],
        action_items=[{"text": "play it slowly", "link_index": 1, "lane": "lesson"}],
    )
    composer, etude = link_rows(notes_db, note_id)
    assert (etude["lane"], composer["lane"]) == ("lesson", None)

    by_type = {link.entity_type: link for link in repo.get_note(notes_cfg, USER, note_id).links}
    assert by_type["repertoire"].lane == "lesson"
    assert by_type["composer"].lane is None  # a link with no action item
    [item] = repo.by_entity(notes_cfg, USER, "repertoire", 35).items
    assert [link.lane for link in item.links] == ["lesson"]


def test_the_lane_column_only_accepts_the_two_lanes(notes_db: FakeDb) -> None:
    note_id = add_note(notes_db)
    add_link(notes_db, note_id, "repertoire", 1, lane="practice")
    with pytest.raises(Exception, match="check"):
        add_link(notes_db, note_id, "repertoire", 2, lane="someday")


def test_a_repeat_confirm_does_not_create_the_backlog_item_again(
    notes_cfg: HostConfig, notes_db: FakeDb, fake_hooks: FakeHooks
) -> None:
    note_id = add_note(notes_db)
    body = {
        "links": [ETUDE],
        "action_items": [
            {"text": "slow", "link_index": 0, "lane": "practice"},
            {"text": "hands apart", "link_index": 0, "lane": "lesson"},
        ],
    }
    assert confirm(notes_cfg, note_id, **body).backlog_created == [100, 101]
    again = confirm(notes_cfg, note_id, **body)
    assert (again.links_created, again.backlog_created) == (0, [])
    assert len(fake_hooks.actions) == 2
    [row] = link_rows(notes_db, note_id)
    assert row["action_item"] == "slow\nhands apart" and row["backlog_id"] == 101
    assert [a[2] for a in fake_hooks.actions] == ["practice", "lesson"]


def test_an_action_with_its_own_entity_creates_the_link(
    notes_cfg: HostConfig, notes_db: FakeDb
) -> None:
    note_id = add_note(notes_db)
    result = confirm(
        notes_cfg,
        note_id,
        action_items=[
            {
                "text": "scales",
                "entity_type": "technique",
                "entity_id": 7,
                "anchor": "warmup",
                "lane": "practice",
            }
        ],
    )
    assert (result.links_created, result.backlog_created) == (1, [100])
    [row] = link_rows(notes_db, note_id)
    assert (row["entity_type"], row["anchor"], row["status"], row["action_item"]) == (
        "technique",
        "warmup",
        "confirmed",
        "scales",
    )


def test_an_action_with_only_an_anchor_joins_the_link_there(
    notes_cfg: HostConfig, notes_db: FakeDb
) -> None:
    note_id = add_note(notes_db)
    link_id = add_link(notes_db, note_id, "repertoire", 35, anchor="etude-3")
    confirm(notes_cfg, note_id, action_items=[{"text": "t", "anchor": "etude-3", "lane": "lesson"}])
    assert link_rows(notes_db, note_id)[0]["id"] == link_id
    assert link_rows(notes_db, note_id)[0]["action_item"] == "t"


def test_action_items_that_cannot_find_a_link_are_422(
    notes_cfg: HostConfig, notes_db: FakeDb, fake_hooks: FakeHooks
) -> None:
    note_id = add_note(notes_db)
    with pytest.raises(repo.ActionNeedsLink) as err:
        confirm(
            notes_cfg, note_id, action_items=[{"text": "t", "anchor": "none", "lane": "practice"}]
        )
    assert (err.value.status, err.value.body["error"]) == (422, "action_needs_link")
    for index in (0, 5, -1):
        with pytest.raises(repo.InvalidLinkIndex):
            confirm(
                notes_cfg,
                note_id,
                links=[],
                action_items=[{"text": "t", "link_index": index, "lane": "practice"}],
            )
    assert fake_hooks.actions == []


def test_a_bad_action_stops_the_good_ones_before_any_hook_runs(
    notes_cfg: HostConfig, notes_db: FakeDb, fake_hooks: FakeHooks
) -> None:
    note_id = add_note(notes_db)
    with pytest.raises(repo.InvalidLinkIndex):
        confirm(
            notes_cfg,
            note_id,
            links=[ETUDE],
            action_items=[
                {"text": "ok", "link_index": 0, "lane": "practice"},
                {"text": "bad", "link_index": 3, "lane": "practice"},
            ],
        )
    assert fake_hooks.actions == [] and link_rows(notes_db, note_id) == []


def test_a_host_without_a_backlog_still_keeps_the_action_text(notes_db: FakeDb) -> None:
    cfg = make_cfg(notes_db, scheme=FakeScheme(), hooks=None)
    note_id = add_note(notes_db)
    result = confirm(
        cfg,
        note_id,
        links=[ETUDE],
        action_items=[{"text": "t", "link_index": 0, "lane": "practice"}],
    )
    assert result.backlog_created == []
    [row] = link_rows(notes_db, note_id)
    assert (row["action_item"], row["backlog_id"]) == ("t", None)


def test_a_failing_backlog_hook_fails_the_confirm_and_rolls_back(
    notes_cfg: HostConfig, notes_db: FakeDb, fake_hooks: FakeHooks
) -> None:
    def boom(*_args: object) -> int:
        raise RuntimeError("backlog down")

    fake_hooks.on_action_item = boom
    note_id = add_note(notes_db)
    with pytest.raises(RuntimeError):
        confirm(
            notes_cfg,
            note_id,
            links=[ETUDE],
            action_items=[{"text": "t", "link_index": 0, "lane": "practice"}],
        )
    assert link_rows(notes_db, note_id) == []


def test_multiline_action_text_is_flattened_so_repeats_still_match(
    notes_cfg: HostConfig, notes_db: FakeDb, fake_hooks: FakeHooks
) -> None:
    note_id = add_note(notes_db)
    body = {
        "links": [ETUDE],
        "action_items": [{"text": "a\nb  c", "link_index": 0, "lane": "practice"}],
    }
    confirm(notes_cfg, note_id, **body)
    confirm(notes_cfg, note_id, **body)
    assert len(fake_hooks.actions) == 1
    assert link_rows(notes_db, note_id)[0]["action_item"] == "a b c"


# --- someday ----------------------------------------------------------------------------------


def test_someday_is_refused_unless_the_host_keeps_it(
    notes_cfg: HostConfig, notes_db: FakeDb, fake_hooks: FakeHooks
) -> None:
    note_id = add_note(notes_db)
    body = {"links": [ETUDE], "someday": [{"mention": "WTC Book 1", "kind_hint": "work"}]}
    with pytest.raises(repo.SomedayUnsupported) as err:
        confirm(notes_cfg, note_id, **body)
    assert (err.value.status, err.value.body) == (422, {"error": "someday_unsupported"})
    assert link_rows(notes_db, note_id) == []

    fake_hooks.enable_someday()  # the hook alone is not enough: the policy must allow it
    with pytest.raises(repo.SomedayUnsupported):
        confirm(notes_cfg, note_id, **body)

    notes_cfg.policy.someday = True
    assert confirm(notes_cfg, note_id, **body).someday_created == 1
    assert fake_hooks.someday == [(USER, note_id, {"mention": "WTC Book 1", "kind_hint": "work"})]


# --- events (K§10) ----------------------------------------------------------------------------


def test_confirm_emits_note_enriched_with_the_k10_counts(
    notes_cfg: HostConfig, notes_db: FakeDb, fake_hooks: FakeHooks
) -> None:
    note_id = add_note(
        notes_db, title="Howat", origin="source", source_system="obsidian", source_workspace="V"
    )
    confirm(
        notes_cfg,
        note_id,
        links=[ETUDE, {"entity_type": "composer", "entity_id": 1}],
        rejected=[{"entity_type": "technique", "entity_id": 7}],
        action_items=[{"text": "t", "link_index": 0, "lane": "practice"}],
        deferred=[{"mention": "Debussy"}],
    )
    [(_, event, entity, _)] = fake_hooks.events
    assert event == "note_enriched"
    assert entity == {
        "entity_type": "note",
        "entity_id": note_id,
        "event": "note_enriched",
        "note_id": note_id,
        "note_title": "Howat",
        "kind": "note",
        "origin": "source",
        "source_system": "obsidian",
        "source_workspace": "V",
        "link_count": 2,
        "attachment_count": 0,
        "links_created": 2,
        "backlog_created": 1,
        "rejected": 1,
        "deferred": 1,
    }


def test_a_confirm_that_changes_nothing_emits_nothing(
    notes_cfg: HostConfig, notes_db: FakeDb, fake_hooks: FakeHooks
) -> None:
    note_id = add_note(notes_db)
    confirm(notes_cfg, note_id, links=[ETUDE])
    fake_hooks.events.clear()
    confirm(notes_cfg, note_id, links=[ETUDE])
    assert fake_hooks.events == []
    confirm(notes_cfg, note_id, deferred=[{"mention": "later"}])  # "decide later" is news
    assert fake_hooks.names() == ["note_enriched"]


# --- by_entity --------------------------------------------------------------------------------


@pytest.fixture
def tree() -> FakeScheme:
    return FakeScheme(
        {
            ("composer", 1): "Chopin",
            ("repertoire", 35): "Études, Op.10",
            ("repertoire", 36): "Études, Op.25",
            ("movement", 12): "Op.10 nº 12",
            ("movement", 3): "Op.10 nº 3",
            ("movement", 50): "Op.25 nº 1",
        },
        kids={
            ("composer", 1): [("repertoire", 35), ("repertoire", 36)],
            ("repertoire", 35): [("movement", 3), ("movement", 12)],
            ("repertoire", 36): [("movement", 50)],
        },
    )


def entity_items(cfg: HostConfig, entity_type: str, entity_id: int, **kw: Any) -> Any:
    return repo.by_entity(cfg, USER, entity_type, entity_id, **kw).items


def test_by_entity_lists_notes_with_the_matching_links(
    notes_cfg: HostConfig, notes_db: FakeDb
) -> None:
    older = add_note(notes_db, title="older", note_date="2026-01-01")
    newer = add_note(notes_db, title="newer", note_date="2026-02-01")
    add_note(notes_db, title="unrelated")
    add_note(notes_db, OTHER, title="theirs")
    add_link(notes_db, older, "repertoire", 35, anchor="a")
    add_link(notes_db, older, "composer", 1)  # same note, another entity: not returned
    add_link(notes_db, newer, "repertoire", 35, anchor="b")
    add_link(notes_db, newer, "repertoire", 35, anchor="c")
    add_link(notes_db, newer, "repertoire", 35, anchor="rejected", status="rejected")
    add_link(notes_db, add_note(notes_db, OTHER), "repertoire", 35, user_id=OTHER)

    items = entity_items(notes_cfg, "repertoire", 35)
    assert [i.note.title for i in items] == ["newer", "older"]
    assert [(link.anchor, link.entity_label, link.via) for link in items[0].links] == [
        ("b", "Études, Op.10", None),
        ("c", "Études, Op.10", None),
    ]
    assert [link.anchor for link in items[1].links] == ["a"]
    assert items[1].note.link_count == 2  # the summary still counts the whole note
    assert len(entity_items(notes_cfg, "repertoire", 35, limit=1)) == 1
    assert entity_items(notes_cfg, "repertoire", 12345) == []


def test_include_children_walks_the_scheme_tree(notes_db: FakeDb, tree: FakeScheme) -> None:
    cfg = make_cfg(notes_db, scheme=tree)
    on_piece = add_note(notes_db, title="piece", note_date="2026-01-01")
    on_movement = add_note(notes_db, title="movement", note_date="2026-01-02")
    on_other_piece = add_note(notes_db, title="op25", note_date="2026-01-03")
    on_composer = add_note(notes_db, title="composer", note_date="2026-01-04")
    add_link(notes_db, on_piece, "repertoire", 35)
    add_link(notes_db, on_movement, "movement", 12)
    add_link(notes_db, on_other_piece, "movement", 50)
    add_link(notes_db, on_composer, "composer", 1)

    # Without the flag only the piece's own links come back.
    assert [i.note.title for i in entity_items(cfg, "repertoire", 35)] == ["piece"]

    piece = {
        i.note.title: i.links for i in entity_items(cfg, "repertoire", 35, include_children=True)
    }
    assert set(piece) == {"piece", "movement"}
    assert piece["piece"][0].via is None  # matched on the entity itself
    assert piece["movement"][0].via.model_dump() == {"entity_type": "movement", "entity_id": 12}

    composer = {
        i.note.title: i.links for i in entity_items(cfg, "composer", 1, include_children=True)
    }
    assert set(composer) == {"composer", "piece", "movement", "op25"}
    assert composer["composer"][0].via is None
    # `via` is the composer's direct child the link sits under: the piece, even for a movement.
    assert composer["piece"][0].via.model_dump() == {"entity_type": "repertoire", "entity_id": 35}
    assert composer["movement"][0].via.model_dump() == {
        "entity_type": "repertoire",
        "entity_id": 35,
    }
    assert composer["op25"][0].via.model_dump() == {"entity_type": "repertoire", "entity_id": 36}


def test_include_children_survives_cycles_and_hosts_that_return_grandchildren(
    notes_db: FakeDb,
) -> None:
    scheme = FakeScheme(
        {("composer", 1): "C", ("repertoire", 2): "R", ("movement", 3): "M"},
        kids={
            ("composer", 1): [("repertoire", 2), ("movement", 3), ("composer", 1)],
            ("repertoire", 2): [("movement", 3), ("composer", 1)],
        },
    )
    cfg = make_cfg(notes_db, scheme=scheme)
    note_id = add_note(notes_db)
    add_link(notes_db, note_id, "movement", 3)
    [item] = entity_items(cfg, "composer", 1, include_children=True)
    assert item.links[0].via.model_dump() == {"entity_type": "movement", "entity_id": 3}


def test_a_host_without_children_just_gets_the_entity(
    notes_cfg: HostConfig, notes_db: FakeDb
) -> None:
    class Plain:
        prefix = "p"
        entity_types = ("repertoire",)

        def resolve(self, user_id: str, entity_type: str, entity_id: int) -> None:
            return None

    cfg = make_cfg(notes_db)
    object.__setattr__(cfg, "schemes", [Plain()])
    note_id = add_note(notes_db)
    add_link(notes_db, note_id, "repertoire", 35)
    assert len(entity_items(cfg, "repertoire", 35, include_children=True)) == 1


def test_tombstoned_notes_stay_reachable_but_orphaned_links_on_live_notes_do_not(
    notes_cfg: HostConfig, notes_db: FakeDb
) -> None:
    dead = add_note(notes_db, title="dead", deleted_at="2026-10-01 10:00:00")
    stale = add_note(notes_db, title="stale")
    add_link(notes_db, dead, "repertoire", 35, status="orphaned")
    add_link(notes_db, stale, "repertoire", 35, status="orphaned")

    [item] = entity_items(notes_cfg, "repertoire", 35)
    assert item.note.title == "dead" and item.note.deleted_at is not None
    assert [link.status for link in item.links] == ["orphaned"]
