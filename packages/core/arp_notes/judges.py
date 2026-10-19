"""Reference judges (K§4): JevChoiceJudge, LlmJudge, ChainJudge. Owner: C5c (ga-mxal.28).

The types below are the exact shapes from K§4. The core imports no provider SDK: the host
injects the provider call into LlmJudge.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

import httpx

JEV_API_URL = "https://api.typesafe.ai/v1/systemone"
# Pinned on purpose: `jev-latest` can change calibration under us (JJF ADR, "Jev facts").
JEV_MODEL = "jev-1.13.0"
NONE_KEY = "none"


class JudgeError(Exception):
    """A judge could not produce a usable Judgement. The pipeline degrades to search-only."""


class JevUnavailableError(JudgeError):
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


class _JudgeLike(Protocol):
    name: str

    def judge(self, mention: Mention, candidates: list[Candidate]) -> Judgement: ...


def _keys(candidates: list[Candidate]) -> dict[str, Candidate]:
    """Choice names for a candidate set: the entity id, or `type:id` when the set mixes types."""
    typed = len({c.entity_type for c in candidates}) > 1
    return {
        (f"{c.entity_type}:{c.entity_id}" if typed else str(c.entity_id)): c for c in candidates
    }


def _describe(c: Candidate) -> str:
    return f"{c.entity_label} ({c.composer_label})" if c.composer_label else c.entity_label


def _clamp(x: Any) -> float:
    try:
        return min(1.0, max(0.0, float(x)))
    except (TypeError, ValueError):
        return 0.0


def _mention_state(mention: Mention, chosen: Candidate | None = None) -> str:
    ctx = mention.context
    lines = [f"Note: {ctx.get('note_title', '')} ({ctx.get('note_kind', '')})"]
    for key in ("composer", "opus"):
        if ctx.get(key):
            lines.append(f"{key.capitalize()} in context: {ctx[key]}")
    lines.append(f"Mention: {mention.text}")
    lines.append(f"Quote: {mention.quote}")
    if chosen is not None:
        lines.append(f"Chosen work: {_describe(chosen)}")
    return "\n".join(lines)


class JevChoiceJudge:
    """One Choice question per stage with an explicit `none` (request shape: JJF jev_client.py).

    Stage 1 picks a work (or `none`); stage 2 picks a movement whenever the chosen work has
    children. `criteria` is an OBJECT {choice_name: description}; a bare string 422s.
    Confidence is Jev's for the last stage asked, floored by stage 1 when a movement is chosen.
    Any transport, HTTP or shape problem, and a missing key, raise JevUnavailableError.
    """

    name = "jev-choice"

    def __init__(
        self,
        api_key: str,
        url: str = JEV_API_URL,
        model: str = JEV_MODEL,
        timeout_s: float = 2.0,
    ) -> None:
        self._api_key = api_key
        self._url = url
        self._model = model
        self._timeout_s = timeout_s

    def judge(self, mention: Mention, candidates: list[Candidate]) -> Judgement:
        if not self._api_key:
            raise JevUnavailableError("Jev API key not configured")
        if not candidates:
            return Judgement(None, 1.0, self.name, "work")
        work, conf = self._ask(
            _mention_state(mention),
            "Which catalogue entry does the mention refer to? Choose none unless one entry "
            "clearly matches.",
            candidates,
        )
        if work is None or not work.children:
            return Judgement(work, conf, self.name, "work")
        movement, mconf = self._ask(
            _mention_state(mention, work),
            "Does the mention refer to one particular movement of the chosen work? Choose "
            "none if it refers to the work as a whole.",
            work.children,
        )
        if movement is None:
            return Judgement(work, conf, self.name, "work")
        return Judgement(movement, min(conf, mconf), self.name, "movement")

    def _ask(
        self, state: str, instructions: str, candidates: list[Candidate]
    ) -> tuple[Candidate | None, float]:
        keyed = _keys(candidates)
        criteria = {k: _describe(c) for k, c in keyed.items()}
        criteria[NONE_KEY] = "None of the listed entries is what the mention refers to."
        payload = {
            "model": self._model,
            "state": state,
            "questions": {
                "pick": {"type": "choice", "instructions": instructions, "criteria": criteria}
            },
        }
        try:
            resp = httpx.post(
                self._url,
                json=payload,
                headers={"Authorization": f"Bearer {self._api_key}"},
                timeout=self._timeout_s,
            )
            resp.raise_for_status()
            answer = resp.json()["answers"]["pick"]
            choice = answer["choice"]
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
            raise JevUnavailableError(f"jev request failed: {exc!r}") from exc
        if choice == NONE_KEY:
            picked = None
        elif choice in keyed:
            picked = keyed[choice]
        else:
            raise JevUnavailableError(f"jev chose {choice!r}, which was not offered")
        conf = answer.get("confidence")
        if conf is None:
            conf = (answer.get("probabilities") or {}).get(choice)
        return picked, _clamp(conf)


class LlmJudge:
    """The host injects the provider call; `complete(prompt) -> text`.

    One flat option list (works, then their movements, each with a unique id); the model
    answers JSON `{"choice": "<id>|none", "confidence": 0..1}`. Malformed output raises
    JudgeError, so a chain keeps the primary result and a bare pipeline degrades to search.
    """

    def __init__(self, complete: Callable[[str], str], name: str) -> None:
        self._complete = complete
        self.name = name

    def judge(self, mention: Mention, candidates: list[Candidate]) -> Judgement:
        if not candidates:
            return Judgement(None, 1.0, self.name, "work")
        flat: list[tuple[Candidate, Literal["work", "movement"]]] = []
        for c in candidates:
            flat.append((c, "work"))
            flat.extend((m, "movement") for m in c.children or [])
        keyed = _keys([c for c, _ in flat])
        stage_of: dict[str, Literal["work", "movement"]] = {
            k: st for k, (_, st) in zip(keyed, flat, strict=True)
        }
        options = "\n".join(f"- {k}: {_describe(c)}" for k, c in keyed.items())
        prompt = (
            "Decide which catalogue entry a note's mention refers to.\n\n"
            f"{_mention_state(mention)}\n\nOptions:\n{options}\n- {NONE_KEY}: no option matches\n\n"
            'Answer with JSON only: {"choice": "<option id or none>", "confidence": <0..1>}. '
            "Prefer a movement only if the mention names one; otherwise pick the work."
        )
        text = self._complete(prompt)
        found = re.search(r"\{.*\}", text, re.DOTALL)
        try:
            if found is None:
                raise ValueError("no JSON object")
            data = json.loads(found.group(0))
            choice = str(data["choice"])
        except (ValueError, KeyError, TypeError) as exc:
            raise JudgeError(f"{self.name}: unparseable answer: {text[:200]!r}") from exc
        conf = _clamp(data.get("confidence"))
        if choice == NONE_KEY:
            return Judgement(None, conf, self.name, "work")
        if choice not in keyed:
            raise JudgeError(f"{self.name}: chose {choice!r}, which was not offered")
        return Judgement(keyed[choice], conf, self.name, stage_of[choice])


class ChainJudge:
    """`primary`, then `escalate` when confidence < `threshold` or the primary raised.

    A failed escalation keeps the primary result; a failed primary with nothing to escalate to
    re-raises (the pipeline then degrades to search-only). `Judgement.judge` records the path,
    e.g. 'jev-choice>haiku'.
    """

    def __init__(
        self,
        primary: _JudgeLike,
        escalate: _JudgeLike | None = None,
        threshold: float = 0.5,
    ) -> None:
        self._primary = primary
        self._escalate = escalate
        self._threshold = threshold
        self.name = primary.name if escalate is None else f"{primary.name}>{escalate.name}"

    def judge(self, mention: Mention, candidates: list[Candidate]) -> Judgement:
        first: Judgement | None = None
        try:
            first = self._primary.judge(mention, candidates)
        except Exception:
            if self._escalate is None:
                raise
        if first is not None and (self._escalate is None or first.confidence >= self._threshold):
            return first
        assert self._escalate is not None
        try:
            second = self._escalate.judge(mention, candidates)
        except Exception:
            if first is None:
                raise
            return first
        return Judgement(
            second.choice, second.confidence, f"{self._primary.name}>{second.judge}", second.stage
        )
