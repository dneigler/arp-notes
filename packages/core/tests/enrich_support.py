"""Fakes for the enrich tests (C5a, ga-mxal.12). Synthetic data only: the fixture is invented text.

`SpikeScheme` stands in for a host's LinkSchemes and mimics the shape of the resolver spike's 15
labelled mentions: three numbering styles, a composer-less opus line, a misspelt composer, catalogue
gaps and a pre-collapsed duplicate triple. It returns PT-shaped plain dicts (string ids, extra
`in_library` / `status` keys).
"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from arp_notes.judges import Candidate, Judgement, Mention

FIXTURES = Path(__file__).parent / "fixtures" / "enrich"
BODY = (FIXTURES / "masterclass.md").read_text("utf-8")


def cand(
    etype: str, eid: Any, label: str, score: float, composer: str | None = None, **extra: Any
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "entity_type": etype,
        "entity_id": eid,
        "entity_label": label,
        "score": score,
        "in_library": True,
        "status": "active",
        **extra,
    }
    if composer:
        out["composer_label"] = composer
    return out


DEBUSSY = cand(
    "repertoire",
    "18",
    "Préludes",
    0.9,
    "Debussy",
    duplicate_group="debussy-preludes",
    duplicates=[
        cand("repertoire", "19", "Préludes (Book 1)", 0.85, "Debussy"),
        cand("repertoire", "26", "Preludes", 0.8, "Debussy"),
    ],
)

# span text (casefolded) -> what the host's reconcile returns for it
TABLE: dict[str, list[dict[str, Any]]] = {
    "op. 10 nº 3": [cand("movement", "103", "Étude Op.10 nº 3", 0.92, "Chopin")],
    "nº 12": [cand("movement", "112", "Étude Op.10 nº 12", 0.9, "Chopin")],
    "op.25 no 1": [cand("movement", "251", "Étude Op.25 nº 1", 0.9, "Chopin")],
    "op. 25 nº 6": [cand("movement", "256", "Étude Op.25 nº 6", 0.88, "Chopin")],
    "bwv 814": [cand("repertoire", "814", "Suite in E minor, BWV 814", 0.95, "Bach")],
    "k.380": [cand("repertoire", "380", "Sonata K. 380", 0.9, "Mozart")],
    "hob.xvi:48": [cand("repertoire", "48", "Sonata Hob. XVI:48", 0.9, "Haydn")],
    "d. 960": [cand("repertoire", "960", "Sonata D. 960", 0.9, "Schubert")],
    "debussy préludes": [DEBUSSY],
    "chopin": [cand("composer", "1", "Chopin", 0.95)],
    "pedaling": [cand("technique", "7", "Pedaling", 0.6)],
}


def norm(span: dict[str, Any]) -> str:
    return str(span["text"]).casefold()


class SpikeScheme:
    prefix = "t"
    entity_types = ("repertoire", "movement", "composer", "technique", "instructor")

    def __init__(self, table: dict[str, list[dict[str, Any]]] | None = None) -> None:
        self.table = TABLE if table is None else table
        self.calls: list[list[dict[str, Any]]] = []

    def resolve(self, user_id: str, entity_type: str, entity_id: int) -> dict[str, Any] | None:
        return None

    def search(
        self, user_id: str, q: str, *, entity_types: Sequence[str] | None = None, limit: int = 20
    ) -> list[dict[str, Any]]:
        return []

    def reconcile(self, user_id: str, spans: Sequence[Any]) -> list[list[dict[str, Any]]]:
        self.calls.append([dict(s) for s in spans])
        return [list(self.table.get(norm(s), [])) for s in spans]


class KeyedScheme(SpikeScheme):
    """Adds `dedupe_key`: rows with equal label-stem keys are duplicates (K§4 step 3)."""

    def dedupe_key(self, candidate: Any) -> str | None:
        label = candidate["entity_label"] if isinstance(candidate, dict) else candidate.entity_label
        return str(label).split(" (")[0].casefold()


Pick = Callable[[Mention, list[Candidate]], Judgement]


class FakeJudge:
    """Calls `pick(mention, candidates)` and records every call. `pick` may raise."""

    def __init__(self, name: str, pick: Pick) -> None:
        self.name = name
        self.pick = pick
        self.calls: list[tuple[Mention, list[Candidate]]] = []

    def judge(self, mention: Mention, candidates: list[Candidate]) -> Judgement:
        self.calls.append((mention, candidates))
        return self.pick(mention, candidates)


def first(confidence: float = 0.9, name: str = "fake") -> Pick:
    """A pick that always chooses the first candidate at `confidence`."""

    def pick(mention: Mention, candidates: list[Candidate]) -> Judgement:
        return Judgement(candidates[0], confidence, name, "work")

    return pick


def dumped(proposal: Any) -> dict[str, Any]:
    return json.loads(proposal.model_dump_json())
