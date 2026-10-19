"""C5b Layer-2 extraction (ADR §3.4 step 2, K§7). Synthetic data only; the model is a fake fn."""

from __future__ import annotations

import json
import logging
from typing import Any

import pytest
from arp_notes.config import HostConfig
from arp_notes.extract import LlmDisabled, extract, merge
from arp_notes.models import Note, Proposal
from arp_notes.ports import Hooks, Policy

BODY = """# Lesson 3

Work on the **Etudes** this week.

## Op. 10 No. 12

Slow the left hand; drop the hand after each run. ^drop-hand

## Pedalling
Half pedal in the middle section.
"""

NOTE = Note.model_validate(
    {
        "id": 7,
        "user_id": "u1",
        "kind": "lesson",
        "title": "Lesson 3",
        "body_md": BODY,
        "frontmatter": {},
        "origin": "source",
        "created_via": "sync",
        "version": 1,
        "created_at": "2026-10-01T10:00:00Z",
        "updated_at": "2026-10-01T10:00:00Z",
        "attachments": [],
        "links": [],
        "review_pending": 0,
    }
)

LINK = {
    "entity_type": "repertoire",
    "entity_id": 35,
    "entity_label": "Etudes, Op. 10",
    "anchor": "op-10-no-12",
    "quote": "Op. 10 No. 12",
    "confidence": 0.9,
    "proposed_by": "resolver",
    "reason": "title match",
}
PROPOSAL = Proposal.model_validate(
    {
        "note_id": 7,
        "links": [LINK],
        "action_items": [],
        "takeaways": [],
        "unresolved": [],
        "generated_by": ["resolver"],
        "cached": False,
        "proposed_at": None,
    }
)

GOOD = {
    "takeaways": [{"anchor": "pedalling", "comment": "Half pedal in the middle section."}],
    "action_items": [
        {
            "text": "Practise Nº 12 slowly; drop the hand",
            "anchor": "^drop-hand",
            "entity": "repertoire:35",
            "lane": "practice",
        }
    ],
}


def cfg_with(complete: Any = None, *, enrich: bool = True, hooks: bool = True) -> HostConfig:
    return HostConfig(
        db=None,  # type: ignore[arg-type]  # extract touches no port but Policy and Hooks
        principal=None,  # type: ignore[arg-type]
        storage=None,  # type: ignore[arg-type]
        signer=None,  # type: ignore[arg-type]
        schemes=[],
        policy=Policy(llm_enrich=enrich),
        hooks=Hooks(llm_complete=complete) if hooks else None,
    )


def answering(text: str) -> tuple[Any, list[str]]:
    prompts: list[str] = []

    def complete(prompt: str) -> str:
        prompts.append(prompt)
        return text

    return complete, prompts


# --- valid output ------------------------------------------------------------------------------


def test_valid_json() -> None:
    complete, _ = answering(json.dumps(GOOD))
    out = extract(cfg_with(complete), NOTE, PROPOSAL)
    assert out["takeaways"] == [
        {"anchor": "pedalling", "comment": "Half pedal in the middle section."}
    ]
    [action] = out["action_items"]
    assert action.model_dump() == {
        "text": "Practise Nº 12 slowly; drop the hand",
        "anchor": "^drop-hand",
        "entity_type": "repertoire",
        "entity_id": 35,
        "lane": "practice",
        "proposed_by": "llm",
    }


def test_json_inside_a_code_fence() -> None:
    complete, _ = answering("Here you go:\n```json\n" + json.dumps(GOOD) + "\n```")
    out = extract(cfg_with(complete), NOTE, PROPOSAL)
    assert len(out["takeaways"]) == 1 and len(out["action_items"]) == 1


def test_prompt_carries_note_anchors_and_entities() -> None:
    complete, prompts = answering(json.dumps(GOOD))
    extract(cfg_with(complete), NOTE, PROPOSAL)
    [prompt] = prompts
    assert "Slow the left hand" in prompt
    for anchor in ("lesson-3", "op-10-no-12", "pedalling", "^drop-hand"):
        assert f"- {anchor}" in prompt
    assert "repertoire:35: Etudes, Op. 10" in prompt
    assert "$" not in prompt.split("<<<NOTE")[0]  # every template slot was filled


def test_long_note_is_cut() -> None:
    long = NOTE.model_copy(update={"body_md": "x" * 100_000})
    complete, prompts = answering(json.dumps(GOOD))
    extract(cfg_with(complete), long, PROPOSAL)
    assert len(prompts[0]) < 50_000


# --- output the model got wrong: dropped, never raised -----------------------------------------


@pytest.mark.parametrize(
    "text",
    ["not json at all", "{broken", "[]", '{"takeaways": "no", "action_items": 3}', ""],
)
def test_malformed_json_is_empty_and_warns(text: str, caplog: pytest.LogCaptureFixture) -> None:
    complete, _ = answering(text)
    with caplog.at_level(logging.WARNING, logger="arp_notes.extract"):
        out = extract(cfg_with(complete), NOTE, PROPOSAL)
    assert out == {"takeaways": [], "action_items": []}
    assert "no usable LLM output" in caplog.text


def test_provider_error_is_empty_and_warns(caplog: pytest.LogCaptureFixture) -> None:
    def boom(_: str) -> str:
        raise TimeoutError("provider down")

    with caplog.at_level(logging.WARNING, logger="arp_notes.extract"):
        out = extract(cfg_with(boom), NOTE, PROPOSAL)
    assert out == {"takeaways": [], "action_items": []}
    assert "provider down" in caplog.text


def test_bad_items_are_dropped_and_bad_references_cleared() -> None:
    data = {
        "takeaways": [
            {"comment": "   "},
            {"comment": 5},
            "a string",
            {"anchor": "no-such-heading", "comment": "Keep the wrist loose."},
        ],
        "action_items": [
            {"text": "no lane"},
            {"text": "wrong lane", "lane": "someday"},
            {"lane": "lesson"},
            {
                "text": "Ask about fingering",
                "lane": "lesson",
                "anchor": "nope",
                "entity": "repertoire:999",
            },
        ],
    }
    complete, _ = answering(json.dumps(data))
    out = extract(cfg_with(complete), NOTE, PROPOSAL)
    assert out["takeaways"] == [{"anchor": None, "comment": "Keep the wrist loose."}]
    [action] = out["action_items"]
    assert (action.text, action.lane) == ("Ask about fingering", "lesson")
    assert (action.anchor, action.entity_type, action.entity_id) == (None, None, None)


def test_each_list_is_capped() -> None:
    data = {"takeaways": [{"comment": f"point {i}"} for i in range(20)], "action_items": []}
    complete, _ = answering(json.dumps(data))
    assert len(extract(cfg_with(complete), NOTE, PROPOSAL)["takeaways"]) == 8


# --- disabled path -----------------------------------------------------------------------------


def test_disabled_when_policy_off() -> None:
    complete, prompts = answering(json.dumps(GOOD))
    with pytest.raises(LlmDisabled):
        extract(cfg_with(complete, enrich=False), NOTE, PROPOSAL)
    assert prompts == []


def test_disabled_when_hook_missing() -> None:
    with pytest.raises(LlmDisabled):
        extract(cfg_with(None), NOTE, PROPOSAL)
    with pytest.raises(LlmDisabled):
        extract(cfg_with(None, hooks=False), NOTE, PROPOSAL)


# --- merge into a Proposal ---------------------------------------------------------------------


def test_merge_marks_llm_and_appends() -> None:
    complete, _ = answering(json.dumps(GOOD))
    merged = merge(PROPOSAL, extract(cfg_with(complete), NOTE, PROPOSAL))
    assert merged.generated_by == ["resolver", "llm"]
    assert merged.takeaways == ["Half pedal in the middle section."]
    assert [a.proposed_by for a in merged.action_items] == ["llm"]
    assert merged.links == PROPOSAL.links
    assert PROPOSAL.generated_by == ["resolver"]  # the input is not mutated


def test_merge_of_an_empty_result_still_records_the_attempt() -> None:
    merged = merge(PROPOSAL, {"takeaways": [], "action_items": []})
    assert merged.generated_by == ["resolver", "llm"]
    assert merged.takeaways == [] and merged.action_items == []


def test_merge_skips_what_the_proposal_already_has() -> None:
    complete, _ = answering(json.dumps(GOOD))
    result = extract(cfg_with(complete), NOTE, PROPOSAL)
    once = merge(PROPOSAL, result)
    twice = merge(once, result)
    assert twice.action_items == once.action_items and twice.takeaways == once.takeaways
