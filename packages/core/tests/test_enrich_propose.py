"""C5a propose(): candidates -> collapse -> judge -> escalate (K§4, K§12.2). Synthetic data only."""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import Any

import jsonschema
import pytest
from arp_notes import schemas
from arp_notes.anchors import slug
from arp_notes.config import HostConfig
from arp_notes.enrich import Thresholds, propose
from arp_notes.extract import LlmDisabled
from arp_notes.judges import Candidate, ChainJudge, JevUnavailableError, Judgement, Mention
from arp_notes.models import Proposal, ProposedLink
from arp_notes.ports import Policy
from arp_notes.repo import NoteNotFound
from arp_notes.testing.fakedb import FakeDb
from enrich_support import (
    BODY,
    FakeJudge,
    KeyedScheme,
    SpikeScheme,
    cand,
    dumped,
    first,
)
from repo_support import OTHER, USER, FakeHooks, add_link, add_note, make_cfg


def build(
    db: FakeDb,
    *,
    body: str = BODY,
    scheme: Any = None,
    schemes: list[Any] | None = None,
    judge: Any = None,
    hooks: Any = None,
    policy: Policy | None = None,
    user: str = USER,
    **cols: Any,
) -> tuple[HostConfig, int]:
    cfg = make_cfg(db, hooks=hooks, policy=policy)
    cfg = dataclasses.replace(cfg, judge=judge, schemes=schemes or [scheme or SpikeScheme()])
    note_id = add_note(
        db, user, title="Synthetic masterclass", kind="masterclass", body_md=body, **cols
    )
    return cfg, note_id


def run(db: FakeDb, **kw: Any) -> Proposal:
    cfg, note_id = build(db, **kw)
    return propose(cfg, USER, note_id)


def ids(links: list[ProposedLink]) -> set[tuple[str, int]]:
    return {(link.entity_type, link.entity_id) for link in links}


def plain(p: Proposal) -> list[ProposedLink]:
    return [link for link in p.links if not link.candidates]


def ambiguous(p: Proposal) -> list[ProposedLink]:
    return [link for link in p.links if link.candidates]


def by_id(p: Proposal, etype: str, eid: int) -> ProposedLink:
    [link] = [x for x in p.links if (x.entity_type, x.entity_id) == (etype, eid)]
    return link


PLAIN_IDS = {
    ("movement", 103),
    ("movement", 112),
    ("movement", 251),
    ("movement", 256),
    ("repertoire", 814),
    ("repertoire", 380),
    ("repertoire", 48),
    ("repertoire", 960),
    ("composer", 1),
    ("technique", 7),
}


# --- search-only: the candidate stage carries recall -------------------------------------------


def test_search_only_proposal_for_the_fixture(notes_db: FakeDb) -> None:
    """Search-only keeps explicit catalogue gaps and coordinated names for review."""
    cfg, note_id = build(notes_db)
    p = propose(cfg, USER, note_id)
    assert ids(plain(p)) == PLAIN_IDS
    [debussy] = ambiguous(p)
    assert (debussy.entity_type, debussy.entity_id) == ("repertoire", 18)
    assert debussy.candidates is not None
    assert [(c.entity_id, c.duplicate_group) for c in debussy.candidates] == [
        (18, "debussy-preludes"),
        (19, "debussy-preludes"),
        (26, "debussy-preludes"),
    ]
    assert [u.mention for u in p.unresolved] == [
        "Chopin Études",
        "S. 141",
        "second movement of the Moonlit Sonata",
        "E major Nocturne",
        "WTC Book 1",
        "Op. 110",
        "Fauré",
        "Duparc",
    ]
    assert (p.generated_by, p.action_items, p.takeaways, p.cached) == (["resolver"], [], [], False)
    assert p.proposed_at is not None and p.note_id == note_id


def test_the_proposal_validates_against_the_generated_schema(notes_db: FakeDb) -> None:
    cfg, note_id = build(notes_db)
    out = dumped(propose(cfg, USER, note_id))
    schema = json.loads((Path(schemas.__file__).parent / "proposal.json").read_text("utf-8"))
    jsonschema.validate(out, schema)
    Proposal.model_validate(out)


def test_search_only_links_carry_the_generator_score(notes_db: FakeDb) -> None:
    cfg, note_id = build(notes_db)
    p = propose(cfg, USER, note_id)
    link = by_id(p, "movement", 103)
    assert link.confidence == pytest.approx(0.92)
    assert link.proposed_by == "resolver"
    assert link.anchor == "^e3"
    assert link.quote == "Chopin Op. 10 nº 3 is an operatic piece"
    assert "search" in link.reason
    assert link.entity_label == "Étude Op.10 nº 3"


def test_every_distinct_span_is_sent_to_the_host_once(notes_db: FakeDb) -> None:
    scheme = SpikeScheme()
    cfg, note_id = build(notes_db, scheme=scheme, body="# A\nOp. 10 nº 3\n# B\nOp. 10 nº 3 again\n")
    p = propose(cfg, USER, note_id)
    [calls] = scheme.calls
    assert [s["text"] for s in calls] == ["Op. 10 nº 3"]
    assert [(link.entity_id, link.anchor) for link in p.links] == [(103, "a"), (103, "b")]


def test_a_repeat_under_one_anchor_is_one_link(notes_db: FakeDb) -> None:
    cfg, note_id = build(notes_db, body="# A\nOp. 10 nº 3 and later Op. 10 nº 3 again\n")
    assert len(propose(cfg, USER, note_id).links) == 1


def test_composer_links_are_note_level_with_a_mention_count(notes_db: FakeDb) -> None:
    cfg, note_id = build(notes_db)
    composer = by_id(propose(cfg, USER, note_id), "composer", 1)
    assert composer.mention_count == 2
    assert composer.anchor == "^e3"  # first mention


def test_only_explicit_coordinated_names_survive_without_host_candidates(notes_db: FakeDb) -> None:
    """Generic recall names are dropped; an explicit pair remains reviewable."""
    mentions = [u.mention for u in run(notes_db).unresolved]
    assert not {"Bach", "Mozart", "Haydn", "Beethovan", "Ada Quill"} & set(mentions)
    assert {"Fauré", "Duparc"} <= set(mentions)


def test_unresolved_carries_kind_hint_and_composer_label(notes_db: FakeDb) -> None:
    p = run(notes_db)
    by_text = {u.mention: u for u in p.unresolved}
    assert by_text["Op. 110"].composer_label == "Beethovan"  # a misspelling survives as written
    assert by_text["Op. 110"].kind_hint == "work"
    assert by_text["S. 141"].composer_label is None
    assert by_text["second movement of the Moonlit Sonata"].kind_hint == "movement"
    assert all(u.candidates == [] for u in p.unresolved)


def test_propose_never_writes(notes_db: FakeDb) -> None:
    cfg, note_id = build(notes_db)
    before = notes_db.run("SELECT proposal, proposed_at, review_pending FROM notes", [])
    propose(cfg, USER, note_id, refresh=True)
    assert notes_db.run("SELECT proposal, proposed_at, review_pending FROM notes", []) == before
    assert notes_db.run("SELECT id FROM note_links", []) == []


def test_unknown_and_foreign_notes_are_not_found(notes_db: FakeDb) -> None:
    cfg, note_id = build(notes_db, user=OTHER)
    with pytest.raises(NoteNotFound):
        propose(cfg, USER, note_id)
    with pytest.raises(NoteNotFound):
        propose(cfg, USER, note_id + 99)


def test_a_note_with_nothing_to_find_does_not_call_the_host(notes_db: FakeDb) -> None:
    scheme = SpikeScheme()
    cfg, note_id = build(notes_db, scheme=scheme, body="just words here\n")
    p = propose(cfg, USER, note_id)
    assert (p.links, p.unresolved, scheme.calls) == ([], [], [])


# --- duplicate collapse -------------------------------------------------------------------------


def preludes(*labels: str) -> list[dict[str, Any]]:
    return [cand("repertoire", 10 + i, label, 0.9 - i * 0.01) for i, label in enumerate(labels)]


def test_equal_dedupe_keys_collapse_before_the_judge_sees_them(notes_db: FakeDb) -> None:
    table = {"debussy préludes": preludes("Préludes", "Préludes (Book 1)", "Préludes (2)")}
    judge = FakeJudge("fake", first(0.9))
    cfg, note_id = build(notes_db, scheme=KeyedScheme(table), judge=judge)
    p = propose(cfg, USER, note_id)
    [(mention, offered)] = judge.calls
    assert mention.text == "Debussy Préludes"
    assert [c.entity_id for c in offered] == [10]  # one representative for the cluster
    [pick] = ambiguous(p)  # K§4 step 6: the user links one
    assert pick.candidates is not None
    assert [(c.entity_id, c.duplicate_group) for c in pick.candidates] == [
        (10, "dup:préludes"),
        (11, "dup:préludes"),
        (12, "dup:préludes"),
    ]
    assert "same" in pick.reason


def test_a_collapsed_cluster_beside_another_entry_lists_both(notes_db: FakeDb) -> None:
    rows = [*preludes("Préludes", "Préludes (Book 1)"), cand("repertoire", 40, "Images", 0.5)]
    cfg, note_id = build(notes_db, scheme=KeyedScheme({"debussy préludes": rows}))
    [pick] = ambiguous(propose(cfg, USER, note_id))
    assert pick.candidates is not None
    assert [(c.entity_id, c.duplicate_group) for c in pick.candidates] == [
        (10, "dup:préludes"),
        (11, "dup:préludes"),
        (40, None),
    ]


def test_rows_without_a_key_are_not_collapsed(notes_db: FakeDb) -> None:
    table = {"debussy préludes": preludes("Préludes", "Préludes (Book 1)")}
    cfg, note_id = build(notes_db, scheme=SpikeScheme(table))  # no dedupe_key on this scheme
    [pick] = ambiguous(propose(cfg, USER, note_id))
    assert pick.candidates is not None
    assert [c.duplicate_group for c in pick.candidates] == [None, None]
    assert "different entries" in pick.reason


def test_dedupe_key_is_never_called_on_a_host_collapsed_cluster(notes_db: FakeDb) -> None:
    seen: list[Any] = []

    class Recording(KeyedScheme):
        def dedupe_key(self, candidate: Any) -> str | None:
            seen.append(candidate["entity_id"])
            return super().dedupe_key(candidate)

    cfg, note_id = build(notes_db, scheme=Recording())
    propose(cfg, USER, note_id)
    assert not {"18", "19", "26"} & set(seen)
    assert {"103", "814"} <= set(seen)  # every other candidate was asked


def test_a_host_cluster_is_kept_together_with_or_without_the_judge(notes_db: FakeDb) -> None:
    judge = FakeJudge("fake", first(0.95))
    cfg, note_id = build(notes_db, judge=judge)
    [pick] = ambiguous(propose(cfg, USER, note_id))
    assert pick.confidence == pytest.approx(0.95)
    assert pick.candidates is not None and len(pick.candidates) == 3
    [offered] = [c for m, c in judge.calls if m.text == "Debussy Préludes"]
    assert [(c.entity_id, c.duplicate_group) for c in offered] == [(18, "debussy-preludes")]
    assert [d.entity_id for d in offered[0].duplicates or []] == [19, 26]


# --- the judge ---------------------------------------------------------------------------------


def test_the_judge_confirms_and_its_confidence_replaces_the_score(notes_db: FakeDb) -> None:
    judge = FakeJudge("fake", first(0.97))
    p = run(notes_db, judge=judge)
    link = by_id(p, "movement", 103)
    assert link.confidence == pytest.approx(0.97)
    assert "fake" in link.reason
    assert ids(plain(p)) == PLAIN_IDS
    assert len(ambiguous(p)) == 1


def test_the_judge_sees_the_mention_with_its_carried_context(notes_db: FakeDb) -> None:
    judge = FakeJudge("fake", first())
    run(notes_db, judge=judge)
    seen = {m.text: m for m, _ in judge.calls}
    assert seen["Nº 12"] == Mention(
        text="Nº 12",
        quote="Nº 12 needs the hand dropped; practise it slowly with half pedaling",
        anchor="chopin-études",
        context={
            "note_title": "Synthetic masterclass",
            "note_kind": "masterclass",
            "composer": "Chopin",
            "opus": "Op. 10",
        },
    )
    assert "S. 141" not in seen  # no candidates, nothing to judge


def test_judge_none_makes_structural_spans_unresolved_and_drops_the_rest(
    notes_db: FakeDb,
) -> None:
    def none(mention: Mention, candidates: list[Candidate]) -> Judgement:
        return Judgement(None, 0.9, "fake", "work")

    p = run(notes_db, judge=FakeJudge("fake", none))
    assert p.links == []  # composer and technique spans are recall-only: dropped
    un = {u.mention: u for u in p.unresolved}
    assert "Op. 10 nº 3" in un and "S. 141" in un
    assert [(c.entity_id, c.confidence) for c in un["Op. 10 nº 3"].candidates] == [(103, 0.92)]
    assert un["Op. 10 nº 3"].composer_label == "Chopin"
    assert "found no match" not in str(un["S. 141"])


def test_a_judge_that_raises_degrades_to_search_only_and_is_not_asked_again(
    notes_db: FakeDb,
) -> None:
    def boom(mention: Mention, candidates: list[Candidate]) -> Judgement:
        raise JevUnavailableError("down")

    judge = FakeJudge("fake", boom)
    cfg, note_id = build(notes_db, judge=judge)
    p = propose(cfg, USER, note_id)
    assert len(judge.calls) == 1  # one timeout, not one per mention
    assert ids(plain(p)) == PLAIN_IDS and len(ambiguous(p)) == 1
    assert by_id(p, "movement", 103).confidence == pytest.approx(0.92)


def test_a_judge_that_returns_an_unoffered_entity_degrades_for_that_span(notes_db: FakeDb) -> None:
    def stray(mention: Mention, candidates: list[Candidate]) -> Judgement:
        return Judgement(Candidate("repertoire", 9999, "Stranger", 0.9), 0.9, "fake", "work")

    p = run(notes_db, judge=FakeJudge("fake", stray))
    assert 9999 not in {link.entity_id for link in p.links}
    assert ids(plain(p)) == PLAIN_IDS


def test_low_confidence_without_an_escalation_is_ambiguous_never_dropped(
    notes_db: FakeDb,
) -> None:
    p = run(notes_db, judge=FakeJudge("fake", first(0.3)))
    assert plain(p) == []
    assert {(link.entity_type, link.entity_id) for link in p.links} >= PLAIN_IDS
    link = by_id(p, "movement", 103)
    assert link.confidence == pytest.approx(0.3)
    assert link.candidates is not None and [c.entity_id for c in link.candidates] == [103]
    assert "pick" in link.reason


def test_the_threshold_is_configurable(notes_db: FakeDb) -> None:
    cfg, note_id = build(notes_db, judge=FakeJudge("fake", first(0.9)))
    assert by_id(propose(cfg, USER, note_id), "movement", 103).candidates is None
    strict = propose(cfg, USER, note_id, thresholds=Thresholds(judge=0.95))
    assert by_id(strict, "movement", 103).candidates is not None


def test_the_chain_escalates_below_the_threshold(notes_db: FakeDb) -> None:
    primary = FakeJudge("jev", first(0.3, "jev"))
    escalate = FakeJudge("haiku", first(0.92, "haiku"))
    chain = ChainJudge(primary, escalate, threshold=0.5)
    p = run(notes_db, judge=chain)
    assert len(escalate.calls) == len(primary.calls) > 5
    link = by_id(p, "movement", 103)
    assert link.candidates is None and link.confidence == pytest.approx(0.92)
    assert "jev>haiku" in link.reason


def test_the_chain_does_not_escalate_when_the_primary_is_sure(notes_db: FakeDb) -> None:
    escalate = FakeJudge("haiku", first(0.92, "haiku"))
    chain = ChainJudge(FakeJudge("jev", first(0.8, "jev")), escalate, threshold=0.5)
    run(notes_db, judge=chain)
    assert escalate.calls == []


def test_a_movement_choice_links_the_movement(notes_db: FakeDb) -> None:
    movement = cand("movement", 103, "Étude Op.10 nº 3", 0.9)
    work = cand("repertoire", 35, "Études, Op.10", 0.9, children=[movement])
    table = {"op. 10 nº 3": [work]}

    def pick(mention: Mention, candidates: list[Candidate]) -> Judgement:
        assert candidates[0].children is not None
        return Judgement(candidates[0].children[0], 0.88, "fake", "movement")

    body = "# H\nOp. 10 nº 3 sings\n"
    p = run(notes_db, body=body, scheme=SpikeScheme(table), judge=FakeJudge("f", pick))
    [link] = p.links
    assert (link.entity_type, link.entity_id, link.confidence) == ("movement", 103, 0.88)
    assert link.candidates is None


def test_use_judge_false_is_search_only(notes_db: FakeDb) -> None:
    judge = FakeJudge("fake", first())
    cfg, note_id = build(notes_db, judge=judge)
    p = propose(cfg, USER, note_id, use_judge=False)
    assert judge.calls == []
    assert by_id(p, "movement", 103).confidence == pytest.approx(0.92)


# --- several schemes, coercion, loud failures ---------------------------------------------------


def test_several_schemes_are_concatenated_and_sorted_by_score(notes_db: FakeDb) -> None:
    low = SpikeScheme({"op. 10 nº 3": [cand("movement", 7, "Weak", 0.4)]})
    high = SpikeScheme({"op. 10 nº 3": [cand("movement", 8, "Strong", 0.9)]})
    cfg, note_id = build(notes_db, body="# H\nOp. 10 nº 3\n", schemes=[low, high])
    [link] = propose(cfg, USER, note_id).links
    assert link.entity_id == 8 and link.candidates is not None
    assert [c.entity_id for c in link.candidates] == [8, 7]


def test_plain_dicts_dataclasses_and_string_ids_are_all_accepted(notes_db: FakeDb) -> None:
    table: dict[str, list[Any]] = {
        "op. 10 nº 3": [Candidate("movement", 103, "As a dataclass", 0.9)],
        "bwv 814": [cand("repertoire", " 814 ", "As a padded string", 0.9, extra="ignored")],
        "k.380": [cand("repertoire", 380.0, "As a float", 0.9)],
    }
    body = "# H\nOp. 10 nº 3, BWV 814 and K.380\n"
    p = run(notes_db, body=body, scheme=SpikeScheme(table))
    assert ids(p.links) == {("movement", 103), ("repertoire", 814), ("repertoire", 380)}


@pytest.mark.parametrize("bad", ["a-slug", True, 3.5, None, "12abc"])
def test_a_non_integer_entity_id_raises_naming_the_scheme(notes_db: FakeDb, bad: Any) -> None:
    table = {"op. 10 nº 3": [cand("movement", bad, "Broken", 0.9)]}
    cfg, note_id = build(notes_db, body="# H\nOp. 10 nº 3\n", scheme=SpikeScheme(table))
    with pytest.raises(ValueError, match=r"scheme 't'"):
        propose(cfg, USER, note_id)


def test_a_candidate_without_a_label_raises_naming_the_scheme(notes_db: FakeDb) -> None:
    table = {"op. 10 nº 3": [{"entity_type": "movement", "entity_id": 1, "score": 0.9}]}
    cfg, note_id = build(notes_db, body="Op. 10 nº 3\n", scheme=SpikeScheme(table))
    with pytest.raises(ValueError, match=r"scheme 't'.*entity_label"):
        propose(cfg, USER, note_id)


def test_a_wrong_length_reconcile_result_raises_naming_the_scheme(notes_db: FakeDb) -> None:
    class Short(SpikeScheme):
        prefix = "shorty"

        def reconcile(self, user_id: str, spans: Any) -> list[list[dict[str, Any]]]:
            return [[]]

    cfg, note_id = build(notes_db, scheme=Short())
    with pytest.raises(ValueError, match=r"scheme 'shorty'.*1 lists for \d+ spans"):
        propose(cfg, USER, note_id)


# --- the diff rule -----------------------------------------------------------------------------


def test_confirmed_and_rejected_pairs_are_not_proposed_again(notes_db: FakeDb) -> None:
    cfg, note_id = build(notes_db)
    add_link(notes_db, note_id, "movement", 103, anchor="^e3", status="confirmed")
    add_link(notes_db, note_id, "movement", 256, anchor=slug("Chopin Études"), status="rejected")
    p = propose(cfg, USER, note_id)
    assert ids(plain(p)) == PLAIN_IDS - {("movement", 103), ("movement", 256)}


def test_the_same_entity_at_another_anchor_is_still_proposed(notes_db: FakeDb) -> None:
    cfg, note_id = build(notes_db)
    add_link(notes_db, note_id, "movement", 112, anchor="elsewhere", status="confirmed")
    add_link(notes_db, note_id, "movement", 251, anchor=slug("Chopin Études"), status="orphaned")
    p = propose(cfg, USER, note_id)
    assert {("movement", 112), ("movement", 251)} <= ids(plain(p))


def test_another_notes_links_do_not_suppress(notes_db: FakeDb) -> None:
    cfg, note_id = build(notes_db)
    other = add_note(notes_db, title="other")
    add_link(notes_db, other, "movement", 103, anchor="^e3", status="confirmed")
    assert ("movement", 103) in ids(plain(propose(cfg, USER, note_id)))


def test_a_confirmed_composer_is_not_proposed_at_any_anchor(notes_db: FakeDb) -> None:
    cfg, note_id = build(notes_db)
    add_link(notes_db, note_id, "composer", 1, anchor=None, status="confirmed")
    assert ("composer", 1) not in ids(propose(cfg, USER, note_id).links)


def test_a_cluster_the_user_already_picked_from_is_not_asked_again(notes_db: FakeDb) -> None:
    cfg, note_id = build(notes_db)
    add_link(notes_db, note_id, "repertoire", 19, anchor=slug("Debussy"), status="confirmed")
    assert ambiguous(propose(cfg, USER, note_id)) == []


def test_a_rejected_cluster_member_leaves_the_others_pickable(notes_db: FakeDb) -> None:
    cfg, note_id = build(notes_db)
    add_link(notes_db, note_id, "repertoire", 18, anchor=slug("Debussy"), status="rejected")
    [pick] = ambiguous(propose(cfg, USER, note_id))
    assert pick.candidates is not None
    assert [c.entity_id for c in pick.candidates] == [19, 26]
    assert pick.entity_id == 19  # the headline follows the first survivor


# --- people ------------------------------------------------------------------------------------


def test_a_person_is_one_note_level_link(notes_db: FakeDb) -> None:
    table = {"ada quill": [cand("instructor", "5", "Ada Quill", 0.9)]}
    fm = json.dumps({"presenter": "[[Ada Quill]]"})
    cfg, note_id = build(notes_db, scheme=SpikeScheme(table), frontmatter=fm, person="Ada Quill")
    [link] = propose(cfg, USER, note_id).links
    assert (link.entity_type, link.entity_id, link.anchor) == ("instructor", 5, None)
    assert link.mention_count is None


def test_an_unknown_person_stays_text(notes_db: FakeDb) -> None:
    fm = json.dumps({"presenter": "Ada Quill"})
    p = run(notes_db, frontmatter=fm, person="Ada Quill")
    assert "Ada Quill" not in [u.mention for u in p.unresolved]


def test_a_person_in_the_title_is_looked_up(notes_db: FakeDb) -> None:
    table = {"ada quill": [cand("instructor", "5", "Ada Quill", 0.9)]}
    cfg, note_id = build(notes_db, body="nothing here\n", scheme=SpikeScheme(table))
    notes_db.run(
        "UPDATE notes SET title = %s WHERE id = %s", ["Masterclass with Ada Quill", note_id]
    )
    assert ids(propose(cfg, USER, note_id).links) == {("instructor", 5)}


# --- Layer 2 -----------------------------------------------------------------------------------


def llm_hooks(answer: str) -> FakeHooks:
    hooks = FakeHooks()
    hooks.llm_complete = lambda prompt: answer
    return hooks


def test_llm_true_folds_in_the_extraction(notes_db: FakeDb) -> None:
    answer = json.dumps(
        {
            "takeaways": [{"anchor": "chopin-études", "comment": "Drop the hand after each run"}],
            "action_items": [
                {
                    "text": "Practise Nº 12 slowly",
                    "lane": "practice",
                    "anchor": "chopin-études",
                    "entity": "movement:112",
                }
            ],
        }
    )
    cfg, note_id = build(notes_db, hooks=llm_hooks(answer), policy=Policy(llm_enrich=True))
    p = propose(cfg, USER, note_id, llm=True)
    assert p.generated_by == ["resolver", "llm"]
    [action] = p.action_items
    assert (action.entity_type, action.entity_id, action.lane) == ("movement", 112, "practice")
    assert p.takeaways == ["Drop the hand after each run"]
    assert ids(plain(p)) == PLAIN_IDS


def test_llm_true_needs_the_host_to_enable_it(notes_db: FakeDb) -> None:
    cfg, note_id = build(notes_db)
    with pytest.raises(LlmDisabled):
        propose(cfg, USER, note_id, llm=True)
