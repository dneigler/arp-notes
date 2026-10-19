"""Generated JSON Schemas: no drift, every shape has one valid example, 26-item proposal."""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest
from arp_notes import schemas
from arp_notes.schemas import generate

SCHEMAS_DIR = Path(schemas.__file__).parent
EXAMPLES_DIR = SCHEMAS_DIR / "examples"
SHAPES = generate.shape_models()


def test_checked_in_schemas_equal_the_generated_ones() -> None:
    rendered = generate.render_all()
    on_disk = {p.name: p.read_text("utf-8") for p in SCHEMAS_DIR.glob("*.json")}
    assert on_disk == rendered, "run: python -m arp_notes.schemas.generate"


def test_generate_check_mode_passes() -> None:
    assert generate.main(["--check"]) == 0


def test_every_a2_k2_k6_shape_is_a_model() -> None:
    expected = {
        # A.2 shapes
        *("Note", "NoteSummary", "Attachment", "NoteLink", "ManifestRow", "NoteUpsert"),
        *("UpsertResult", "Proposal", "ProposedLink", "ProposedAction"),
        *("ConfirmBody", "ConfirmResult"),
        # K§12.4 ratified names
        *("ManifestPage", "TombstoneResult", "Capabilities"),
        # K§6.1 / K§6.3
        *("HygieneIssue", "HygieneBlock", "MergePlan"),
    }
    assert expected <= set(SHAPES)


def test_hygiene_schemas_match_the_k61_file_pattern() -> None:
    names = {p.name for p in SCHEMAS_DIR.glob("hygiene_*.json")}
    assert {"hygiene_issue.json", "hygiene_block.json"} <= names


@pytest.mark.parametrize("name", sorted(SHAPES))
def test_schema_is_a_valid_2020_12_document(name: str) -> None:
    schema = json.loads((SCHEMAS_DIR / f"{generate.file_stem(name)}.json").read_text("utf-8"))
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    jsonschema.Draft202012Validator.check_schema(schema)


def test_there_is_exactly_one_example_per_shape() -> None:
    assert {p.stem for p in EXAMPLES_DIR.glob("*.json")} == set(SHAPES)


@pytest.mark.parametrize("name", sorted(SHAPES))
def test_example_validates_against_schema_and_model(name: str) -> None:
    example = json.loads((EXAMPLES_DIR / f"{name}.json").read_text("utf-8"))
    schema = json.loads((SCHEMAS_DIR / f"{generate.file_stem(name)}.json").read_text("utf-8"))
    jsonschema.Draft202012Validator(schema).validate(example)
    SHAPES[name].model_validate(example)


def test_examples_are_synthetic() -> None:
    text = " ".join(p.read_text("utf-8").lower() for p in EXAMPLES_DIR.glob("*.json"))
    assert "howat" not in text
    assert "dneigler" not in text


def test_proposal_example_has_the_review_desk_shape() -> None:
    p = json.loads((EXAMPLES_DIR / "Proposal.json").read_text("utf-8"))
    links = p["links"]
    ambiguous = [lk for lk in links if lk.get("candidates")]
    composers = [lk for lk in links if lk["entity_type"] == "composer"]
    techniques = [lk for lk in links if lk["entity_type"] == "technique"]
    high = [lk for lk in links if lk["confidence"] >= 0.8 and not lk.get("candidates")]
    assert len(high) == 11
    assert len(composers) == 3
    assert len(techniques) == 2
    assert len(ambiguous) == 1
    assert len(p["unresolved"]) == 6
    assert len(p["action_items"]) == 3
    # K§3: 26 distinct reviewable items. The ambiguous link is one of `links`, not an extra.
    assert len(links) + len(p["unresolved"]) + len(p["action_items"]) == 26

    # the duplicate composer pair (Bach 7 / J.S. Bach 11) is two rows for one person
    assert {lk["entity_id"] for lk in composers} == {13, 7, 11}
    assert all(lk["mention_count"] for lk in composers)

    # the ambiguous pick: a duplicate cluster plus one different book
    groups = [c.get("duplicate_group") for c in ambiguous[0]["candidates"]]
    assert groups.count("repertoire:preludes-book-1") == 3
    assert groups.count(None) == 1

    # the six unresolved seeds carry kind_hint, and the work seeds a composer label
    assert all(u["kind_hint"] for u in p["unresolved"])
    assert [u for u in p["unresolved"] if u["kind_hint"] == "work" and u["composer_label"]]
