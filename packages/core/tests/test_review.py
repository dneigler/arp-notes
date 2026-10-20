"""R1 review-state cache: notes.proposal + review_pending (K§3, ga-mxal.29). Synthetic data only."""

from __future__ import annotations

import dataclasses
from typing import Any

import pytest
from arp_notes import repo, review, sync
from arp_notes.config import HostConfig
from arp_notes.models import (
    ConfirmBody,
    ConfirmLink,
    DeferredMention,
    Proposal,
    ProposalCandidate,
    ProposedAction,
    ProposedLink,
    RejectedLink,
    UnresolvedMention,
)
from arp_notes.ports import Policy
from arp_notes.testing.fakedb import FakeDb
from enrich_support import BODY, FakeJudge, SpikeScheme, first
from repo_support import USER, add_note, make_cfg, upsert_body

pytestmark = pytest.mark.usefixtures("signed_urls")

CHANGED = BODY + "\nA closing thought about Pedaling.\n"


def cfg_for(
    db: FakeDb,
    *,
    mode: str = "search",
    scheme: Any = None,
    judge: Any = None,
) -> HostConfig:
    cfg = make_cfg(db, policy=Policy(propose_on_sync=mode))  # type: ignore[arg-type]
    return dataclasses.replace(cfg, schemes=[scheme or SpikeScheme()], judge=judge)


def sync_note(cfg: HostConfig, body_md: str = BODY, doc_id: str = "d1") -> tuple[int, str]:
    result = sync.upsert(cfg, USER, upsert_body(doc_id, body_md, kind="masterclass"))
    return result.note_id, result.outcome


def row(db: FakeDb, note_id: int) -> dict[str, Any]:
    return db.run("SELECT * FROM notes WHERE id = %s", [note_id])[0]


def mockup() -> Proposal:
    """The ReviewDesk proposal: 17 links (one ambiguous), 6 unresolved, 3 actions = 26."""
    links = [
        ProposedLink(
            entity_type="movement",
            entity_id=i,
            entity_label=f"Etude {i}",
            anchor=f"^b{i}",
            quote=f"quote {i}",
            confidence=0.9,
            proposed_by="resolver",
            reason="exact",
        )
        for i in range(1, 17)
    ]
    links.append(
        ProposedLink(
            entity_type="repertoire",
            entity_id=18,
            entity_label="Preludes",
            anchor="^deb",
            quote="Debussy Preludes",
            confidence=0.4,
            proposed_by="resolver",
            reason="three near matches",
            candidates=[
                ProposalCandidate(
                    entity_type="repertoire",
                    entity_id=18,
                    entity_label="Preludes",
                    confidence=0.4,
                )
            ],
        )
    )
    unresolved = [
        UnresolvedMention(
            mention=f"Unknown {i}", anchor=f"^u{i}", quote=f"unknown {i}", candidates=[]
        )
        for i in range(6)
    ]
    actions = [ProposedAction(text=f"do {i}", lane="practice", proposed_by="llm") for i in range(3)]
    return Proposal(
        note_id=0,
        links=links,
        action_items=actions,
        takeaways=[],
        unresolved=unresolved,
        generated_by=["resolver"],
        cached=False,
        proposed_at="2026-10-20T10:00:00",
    )


def cache_mockup(db: FakeDb) -> tuple[HostConfig, int]:
    cfg = cfg_for(db, mode="off")
    note_id = add_note(db, USER, title="Mockup", body_md="x")
    review._store(cfg, USER, note_id, mockup().model_copy(update={"note_id": note_id}))
    return cfg, note_id


# --- the count ---------------------------------------------------------------------------------


def test_the_mockup_scenario_counts_26_before_any_confirm(notes_db: FakeDb) -> None:
    cfg, note_id = cache_mockup(notes_db)
    assert row(notes_db, note_id)["review_pending"] == 26
    cached = review.get_cached(cfg, USER, note_id)
    assert cached is not None and cached.cached is True
    assert (len(cached.links), len(cached.unresolved), len(cached.action_items)) == (17, 6, 3)
    assert cached.proposed_at == "2026-10-20T10:00:00"


def test_get_cached_is_none_before_any_proposal(notes_db: FakeDb) -> None:
    cfg = cfg_for(notes_db)
    assert review.get_cached(cfg, USER, add_note(notes_db, USER)) is None


# --- confirm -----------------------------------------------------------------------------------


def test_confirm_keeps_only_the_deferred_ambiguous_item(notes_db: FakeDb) -> None:
    cfg, note_id = cache_mockup(notes_db)
    body = ConfirmBody(deferred=[DeferredMention(mention="Debussy Preludes", anchor="^deb")])
    assert review.apply_confirm(cfg, USER, note_id, body) == {"review_pending": 1}
    assert row(notes_db, note_id)["review_pending"] == 1
    kept = review.get_cached(cfg, USER, note_id)
    assert kept is not None
    assert [link.quote for link in kept.links] == ["Debussy Preludes"]
    assert (kept.unresolved, kept.action_items, kept.takeaways) == ([], [], [])


def test_confirm_can_defer_an_unresolved_mention(notes_db: FakeDb) -> None:
    cfg, note_id = cache_mockup(notes_db)
    body = ConfirmBody(deferred=[DeferredMention(mention="unknown 2", anchor="^u2")])
    assert review.apply_confirm(cfg, USER, note_id, body) == {"review_pending": 1}
    kept = review.get_cached(cfg, USER, note_id)
    assert kept is not None and [u.mention for u in kept.unresolved] == ["Unknown 2"]


def test_confirm_with_nothing_deferred_clears_the_queue(notes_db: FakeDb) -> None:
    cfg, note_id = cache_mockup(notes_db)
    assert review.apply_confirm(cfg, USER, note_id, ConfirmBody()) == {"review_pending": 0}
    kept = review.get_cached(cfg, USER, note_id)
    assert kept is not None and (kept.links, kept.unresolved, kept.action_items) == ([], [], [])


def test_decide_later_leaves_26_and_reading_the_proposal_does_not_change_it(
    notes_db: FakeDb,
) -> None:
    # "Decide later" makes no call (rule 4); the only thing that can follow is a plain read.
    cfg, note_id = cache_mockup(notes_db)
    served = review.propose(cfg, USER, note_id)
    assert served.cached is True
    assert row(notes_db, note_id)["review_pending"] == 26


def test_a_plain_link_cannot_be_deferred(notes_db: FakeDb) -> None:
    cfg, note_id = cache_mockup(notes_db)
    body = ConfirmBody(deferred=[DeferredMention(mention="quote 1", anchor="^b1")])
    review.apply_confirm(cfg, USER, note_id, body)
    kept = review.get_cached(cfg, USER, note_id)
    assert kept is not None and kept.links == []


def test_confirm_without_a_cache_counts_the_deferred_items(notes_db: FakeDb) -> None:
    cfg = cfg_for(notes_db, mode="off")
    note_id = add_note(notes_db, USER)
    body = ConfirmBody(deferred=[DeferredMention(mention="a", anchor=None)])
    assert review.apply_confirm(cfg, USER, note_id, body) == {"review_pending": 1}
    assert row(notes_db, note_id)["proposal"] is None


# --- auto-propose on sync ----------------------------------------------------------------------


def test_sync_caches_a_search_proposal_and_counts_it(notes_db: FakeDb) -> None:
    cfg = cfg_for(notes_db, mode="search")
    note_id, outcome = sync_note(cfg)
    assert outcome == "created"
    cached = review.get_cached(cfg, USER, note_id)
    assert cached is not None and cached.generated_by == ["resolver"]
    assert row(notes_db, note_id)["review_pending"] == (
        len(cached.links) + len(cached.unresolved) + len(cached.action_items)
    )
    assert row(notes_db, note_id)["review_pending"] > 0


def test_search_mode_never_calls_the_judge_and_judge_mode_does(notes_db: FakeDb) -> None:
    searched = FakeJudge("fake", first())
    sync_note(cfg_for(notes_db, mode="search", judge=searched))
    assert searched.calls == []

    judged = FakeJudge("fake", first())
    sync_note(cfg_for(notes_db, mode="judge", judge=judged), doc_id="d2")
    assert judged.calls


def test_off_mode_caches_nothing(notes_db: FakeDb) -> None:
    cfg = cfg_for(notes_db, mode="off")
    note_id, _ = sync_note(cfg)
    assert row(notes_db, note_id)["proposal"] is None
    assert row(notes_db, note_id)["review_pending"] == 0


def test_an_unchanged_resync_does_not_recompute(notes_db: FakeDb) -> None:
    scheme = SpikeScheme()
    cfg = cfg_for(notes_db, scheme=scheme)
    sync_note(cfg)
    calls = len(scheme.calls)
    _, outcome = sync_note(cfg)
    assert outcome == "unchanged"
    assert len(scheme.calls) == calls


def test_resync_with_a_changed_body_recomputes(notes_db: FakeDb) -> None:
    cfg = cfg_for(notes_db)
    note_id, _ = sync_note(cfg)
    first_stamp = row(notes_db, note_id)["proposed_at"]
    before = review.get_cached(cfg, USER, note_id)
    notes_db.run("UPDATE notes SET proposed_at = %s WHERE id = %s", ["2000-01-01", note_id])
    _, outcome = sync_note(cfg, CHANGED)
    assert outcome == "updated"
    after = review.get_cached(cfg, USER, note_id)
    assert before is not None and after is not None
    assert row(notes_db, note_id)["proposed_at"] > first_stamp.replace(year=2000)
    assert len(after.links) >= len(before.links)


def test_resync_hides_what_was_confirmed_or_rejected(notes_db: FakeDb) -> None:
    cfg = cfg_for(notes_db)
    note_id, _ = sync_note(cfg)
    cached = review.get_cached(cfg, USER, note_id)
    assert cached is not None
    plain = [link for link in cached.links if not link.candidates]
    confirmed, rejected = plain[0], plain[1]
    body = ConfirmBody(
        links=[
            ConfirmLink(
                entity_type=confirmed.entity_type,
                entity_id=confirmed.entity_id,
                anchor=confirmed.anchor,
                quote=confirmed.quote,
            )
        ],
        rejected=[
            RejectedLink(
                entity_type=rejected.entity_type,
                entity_id=rejected.entity_id,
                anchor=rejected.anchor,
            )
        ],
    )
    repo.confirm_links(cfg, USER, note_id, body)
    review.apply_confirm(cfg, USER, note_id, body)

    sync_note(cfg, CHANGED)
    again = review.get_cached(cfg, USER, note_id)
    assert again is not None
    seen = {(link.entity_type, link.entity_id, link.anchor) for link in again.links}
    assert (confirmed.entity_type, confirmed.entity_id, confirmed.anchor) not in seen
    assert (rejected.entity_type, rejected.entity_id, rejected.anchor) not in seen


class Boom(SpikeScheme):
    def reconcile(self, user_id: str, spans: Any) -> Any:
        raise RuntimeError("host is down")


def test_a_propose_failure_does_not_fail_the_upsert(
    notes_db: FakeDb, caplog: pytest.LogCaptureFixture
) -> None:
    cfg = cfg_for(notes_db, scheme=Boom())
    note_id, outcome = sync_note(cfg)
    assert outcome == "created"
    assert row(notes_db, note_id)["proposal"] is None
    assert row(notes_db, note_id)["review_pending"] == 0
    assert "auto-propose failed" in caplog.text


def test_a_failed_recompute_drops_the_stale_cache(notes_db: FakeDb) -> None:
    good = cfg_for(notes_db)
    note_id, _ = sync_note(good)
    assert row(notes_db, note_id)["proposal"] is not None
    _, outcome = sync_note(cfg_for(notes_db, scheme=Boom()), CHANGED)
    assert outcome == "updated"
    assert row(notes_db, note_id)["proposal"] is None
    assert row(notes_db, note_id)["review_pending"] == 0


# --- tombstones --------------------------------------------------------------------------------


def test_tombstone_zeroes_the_count_and_is_never_auto_proposed(notes_db: FakeDb) -> None:
    cfg = cfg_for(notes_db)
    note_id, _ = sync_note(cfg)
    assert row(notes_db, note_id)["review_pending"] > 0
    sync.tombstone(cfg, USER, "obsidian", "Vault", ["d1"])
    assert row(notes_db, note_id)["review_pending"] == 0

    review.after_upsert(cfg, USER, note_id, "updated")
    assert row(notes_db, note_id)["review_pending"] == 0
    review.apply_confirm(cfg, USER, note_id, ConfirmBody())
    assert row(notes_db, note_id)["review_pending"] == 0


def test_a_tombstoned_note_is_not_cached_by_propose(notes_db: FakeDb) -> None:
    cfg = cfg_for(notes_db, mode="off")
    note_id, _ = sync_note(cfg)
    sync.tombstone(cfg, USER, "obsidian", "Vault", ["d1"])
    review.propose(cfg, USER, note_id)
    assert row(notes_db, note_id)["proposal"] is None
    assert row(notes_db, note_id)["review_pending"] == 0


# --- propose through the cache -----------------------------------------------------------------


def test_propose_computes_caches_then_serves_the_cache(notes_db: FakeDb) -> None:
    scheme = SpikeScheme()
    cfg = cfg_for(notes_db, mode="off", scheme=scheme)
    note_id, _ = sync_note(cfg)

    fresh = review.propose(cfg, USER, note_id)
    assert fresh.cached is False
    calls = len(scheme.calls)
    assert row(notes_db, note_id)["review_pending"] > 0

    again = review.propose(cfg, USER, note_id)
    assert again.cached is True
    assert len(scheme.calls) == calls
    assert [link.model_dump() for link in again.links] == [
        link.model_dump() for link in fresh.links
    ]


def test_propose_refresh_recomputes(notes_db: FakeDb) -> None:
    scheme = SpikeScheme()
    cfg = cfg_for(notes_db, scheme=scheme)
    note_id, _ = sync_note(cfg)
    calls = len(scheme.calls)
    refreshed = review.propose(cfg, USER, note_id, refresh=True)
    assert refreshed.cached is False
    assert len(scheme.calls) > calls


def test_propose_after_confirm_serves_only_the_deferred_items(notes_db: FakeDb) -> None:
    cfg, note_id = cache_mockup(notes_db)
    body = ConfirmBody(deferred=[DeferredMention(mention="Debussy Preludes", anchor="^deb")])
    review.apply_confirm(cfg, USER, note_id, body)
    served = review.propose(cfg, USER, note_id)
    assert served.cached is True
    assert [link.quote for link in served.links] == ["Debussy Preludes"]


def test_propose_serves_a_search_only_cache_but_runs_the_judge_on_refresh(
    notes_db: FakeDb,
) -> None:
    judge = FakeJudge("fake", first())
    cfg = cfg_for(notes_db, mode="search", judge=judge)
    note_id, _ = sync_note(cfg)
    review.propose(cfg, USER, note_id)
    assert judge.calls == []
    review.propose(cfg, USER, note_id, refresh=True)
    assert judge.calls


def test_the_hygiene_block_is_not_cached(notes_db: FakeDb) -> None:
    cfg = cfg_for(notes_db)
    note_id, _ = sync_note(cfg)
    assert "hygiene" not in row(notes_db, note_id)["proposal"]
    assert "cached" not in row(notes_db, note_id)["proposal"]


def test_an_unreadable_cache_is_a_miss(notes_db: FakeDb) -> None:
    cfg = cfg_for(notes_db)
    note_id = add_note(notes_db, USER, body_md="x")
    notes_db.run("UPDATE notes SET proposal = '{\"nope\": 1}'::jsonb WHERE id = %s", [note_id])
    assert review.get_cached(cfg, USER, note_id) is None


def test_other_users_notes_are_not_found(notes_db: FakeDb) -> None:
    cfg = cfg_for(notes_db)
    note_id = add_note(notes_db, "someone-else")
    with pytest.raises(repo.NoteNotFound):
        review.get_cached(cfg, USER, note_id)
    with pytest.raises(repo.NoteNotFound):
        review.propose(cfg, USER, note_id)
