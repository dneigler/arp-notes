"""ga-mxal.51: the fixture's optional `merge_pair` makes hygiene.merge_entities_dry_run real."""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from arp_notes.hygiene import fixes
from arp_notes.models import MergeEntitiesApplied
from arp_notes.testing.fakedb import FakeDb
from arp_notes_conformance import DEFAULT, MergePair, load_fixture, suite
from ref_host import TOKEN, make_app

CHECK = "hygiene.merge_entities_dry_run"
PAIR = MergePair("repertoire", 10, (11, 12))


@pytest.fixture
def make(notes_db: FakeDb, tmp_path: Path) -> Callable[..., Any]:
    return lambda **kw: make_app(notes_db, tmp_path / "blobs", **kw)


def run(app: Any, pair: MergePair | None) -> tuple[str, str]:
    fixture = dataclasses.replace(load_fixture(DEFAULT), merge_pair=pair)
    report = suite(app=app, token=TOKEN, fixture=fixture, only=[CHECK], raise_on_failure=False)
    (outcome,) = report.outcomes
    return outcome.status, outcome.detail


def test_a_real_pair_runs_the_dry_run_against_a_merging_host(make: Callable[..., Any]) -> None:
    assert run(make(merging=True), PAIR) == ("passed", "")


def test_without_a_pair_the_placeholder_is_refused_and_the_check_skips(
    make: Callable[..., Any],
) -> None:
    status, detail = run(make(merging=True), None)
    assert status == "skipped"
    assert "merge_pair" in detail


def test_a_host_that_does_not_merge_still_skips_with_a_pair(make: Callable[..., Any]) -> None:
    status, detail = run(make(), PAIR)
    assert status == "skipped"
    assert "501" in detail


def test_a_host_that_refuses_the_named_pair_fails_instead_of_skipping(
    make: Callable[..., Any],
) -> None:
    status, detail = run(make(merging=True), MergePair("repertoire", 10, (99,)))
    assert status == "failed"
    assert "merge-entities" in detail


def test_a_host_that_applies_without_a_token_fails_against_the_real_plan(
    make: Callable[..., Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    app = make(merging=True)
    assert run(app, PAIR)[0] == "passed"
    merge_entities = fixes.merge_entities

    def applies_without_a_token(*args: Any) -> Any:  # (cfg, user, type, keep, ids, dry_run, token)
        if args[5]:
            return merge_entities(*args)
        return MergeEntitiesApplied(applied=True, audit_event_id=1)

    monkeypatch.setattr(fixes, "merge_entities", applies_without_a_token)
    status, detail = run(app, PAIR)
    assert status == "failed"
    assert "without a valid confirm_token" in detail


def test_load_fixture_reads_merge_pair(tmp_path: Path) -> None:
    raw = json.loads((Path(__file__).parents[1] / "fixtures" / "fixture.json").read_text("utf-8"))
    for name in ("masterclass", "corpus", "scratch"):
        raw["documents"][name]["file"] = str(
            Path(__file__).parents[1] / "fixtures" / raw["documents"][name]["file"]
        )
    raw["merge_pair"] = {"entity_type": "repertoire", "keep_id": "18", "merge_ids": [19, "26"]}
    path = tmp_path / "fixture.json"
    path.write_text(json.dumps(raw), "utf-8")
    assert load_fixture(path).merge_pair == MergePair("repertoire", 18, (19, 26))
    assert load_fixture(DEFAULT).merge_pair is None


@pytest.mark.parametrize(
    "pair",
    [
        {"entity_type": "repertoire", "keep_id": 1, "merge_ids": []},
        {"entity_type": "repertoire", "keep_id": 1, "merge_ids": [1]},
    ],
)
def test_load_fixture_rejects_an_unusable_merge_pair(tmp_path: Path, pair: dict[str, Any]) -> None:
    fixtures = Path(__file__).parents[1] / "fixtures"
    raw = json.loads((fixtures / "fixture.json").read_text("utf-8"))
    for spec in raw["documents"].values():
        spec["file"] = str(fixtures / spec["file"])
    raw["merge_pair"] = pair
    path = tmp_path / "fixture.json"
    path.write_text(json.dumps(raw), "utf-8")
    with pytest.raises(ValueError, match="merge_pair"):
        load_fixture(path)
