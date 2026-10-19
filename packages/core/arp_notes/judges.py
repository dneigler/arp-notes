"""Reference judges (K§4): JevChoiceJudge, LlmJudge, ChainJudge. Owner: C5c (ga-mxal.28).

The types below are the exact shapes from K§4. The core imports no provider SDK: the host
injects the provider call into LlmJudge.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal


class JevUnavailableError(Exception):
    """Jev was unreachable, timed out or returned garbage; the pipeline degrades to search-only."""


@dataclass
class Mention:
    text: str
    quote: str
    anchor: str | None = None
    # {composer?, opus?, note_title, note_kind}
    context: dict[str, Any] = field(default_factory=dict)


@dataclass
class Candidate:
    entity_type: str
    entity_id: int
    entity_label: str
    score: float
    duplicate_group: str | None = None
    children: list[Candidate] | None = None  # stage-2 movements
    # K§12.2: feeds unresolved[].composer_label and the "· Debussy" row suffix.
    composer_label: str | None = None
    # K§12.2: the other members of a cluster the host already collapsed.
    duplicates: list[Candidate] | None = None


@dataclass
class Judgement:
    choice: Candidate | None
    confidence: float  # 0..1
    judge: str
    stage: Literal["work", "movement"]


class JevChoiceJudge:
    """One Choice question per stage with an explicit `none` (request shape: JJF jev_client.py)."""

    def __init__(
        self,
        api_key: str,
        url: str,
        model: str = "jev-1.13.0",
        timeout_s: float = 2.0,
    ) -> None:
        raise NotImplementedError("C5c: JevChoiceJudge")

    def judge(self, mention: Mention, candidates: list[Candidate]) -> Judgement:
        raise NotImplementedError("C5c: JevChoiceJudge.judge")


class LlmJudge:
    """The host injects the provider call; `complete(prompt) -> text`."""

    def __init__(self, complete: Callable[[str], str], name: str) -> None:
        raise NotImplementedError("C5c: LlmJudge")

    def judge(self, mention: Mention, candidates: list[Candidate]) -> Judgement:
        raise NotImplementedError("C5c: LlmJudge.judge")


class ChainJudge:
    """`primary`, then `escalate` when confidence < `threshold`."""

    def __init__(
        self,
        primary: Any,
        escalate: Any | None = None,
        threshold: float = 0.5,
    ) -> None:
        raise NotImplementedError("C5c: ChainJudge")

    def judge(self, mention: Mention, candidates: list[Candidate]) -> Judgement:
        raise NotImplementedError("C5c: ChainJudge.judge")
