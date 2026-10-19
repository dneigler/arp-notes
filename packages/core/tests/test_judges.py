"""C5c reference judges (K§4, K§12.3): JevChoiceJudge, LlmJudge, ChainJudge. Synthetic data only."""

from __future__ import annotations

import json

import httpx
import pytest
import respx
from arp_notes.judges import (
    Candidate,
    ChainJudge,
    JevChoiceJudge,
    JevUnavailableError,
    JudgeError,
    Judgement,
    LlmJudge,
    Mention,
)
from arp_notes.ports import Judge

URL = "https://jev.test/v1/systemone"

MENTION = Mention(
    text="Op. 10",
    quote="the Op. 10 etudes are the hard ones",
    context={"composer": "Chopin", "note_title": "Lesson 3", "note_kind": "lesson"},
)
MOVEMENTS = [
    Candidate("movement", 101, "Etude No. 1", 0.6),
    Candidate("movement", 102, "Etude No. 2", 0.5),
]
WORK = Candidate("repertoire", 35, "Etudes, Op. 10", 0.9, children=MOVEMENTS)
OTHER = Candidate("repertoire", 36, "Etudes, Op. 25", 0.7)
LEAF = Candidate("repertoire", 40, "Nocturne in E-flat", 0.8)


def answer(choice: str, confidence: float | None = 0.9, **extra: object) -> httpx.Response:
    body: dict[str, object] = {"choice": choice, **extra}
    if confidence is not None:
        body["confidence"] = confidence
    return httpx.Response(200, json={"answers": {"pick": body}})


def sent(route: respx.Route, i: int = 0) -> dict:
    return json.loads(route.calls[i].request.content)


@pytest.fixture
def jev() -> JevChoiceJudge:
    return JevChoiceJudge("k-123", URL)


# --- names (K§12.3) ---------------------------------------------------------------------------


def test_names() -> None:
    primary = JevChoiceJudge("k", URL)
    haiku = LlmJudge(lambda _: "", "haiku")
    assert primary.name == "jev-choice"
    assert haiku.name == "haiku"
    assert ChainJudge(primary).name == "jev-choice"
    assert ChainJudge(primary, haiku).name == "jev-choice>haiku"
    for j in (primary, haiku, ChainJudge(primary, haiku)):
        assert isinstance(j, Judge)


def test_jev_defaults() -> None:
    j = JevChoiceJudge("k")
    assert (j._url, j._model, j._timeout_s) == (
        "https://api.typesafe.ai/v1/systemone",
        "jev-1.13.0",
        2.0,
    )


# --- JevChoiceJudge ---------------------------------------------------------------------------


@respx.mock
def test_jev_request_shape(jev: JevChoiceJudge) -> None:
    route = respx.post(URL).mock(return_value=answer("40"))
    jev.judge(MENTION, [LEAF, OTHER])
    req = route.calls[0].request
    assert req.headers["authorization"] == "Bearer k-123"
    body = sent(route)
    assert body["model"] == "jev-1.13.0"
    assert "Op. 10" in body["state"] and "Chopin" in body["state"] and "Lesson 3" in body["state"]
    q = body["questions"]["pick"]
    assert q["type"] == "choice"
    assert isinstance(q["criteria"], dict)  # a bare string 422s
    assert list(q["criteria"]) == ["40", "36", "none"]
    assert q["criteria"]["40"] == "Nocturne in E-flat"
    assert all(isinstance(v, str) and v for v in q["criteria"].values())


@respx.mock
def test_jev_picks_a_leaf_work(jev: JevChoiceJudge) -> None:
    route = respx.post(URL).mock(return_value=answer("40", 0.93))
    j = jev.judge(MENTION, [LEAF, OTHER])
    assert j == Judgement(LEAF, 0.93, "jev-choice", "work")
    assert route.call_count == 1  # no children, no stage 2


@respx.mock
def test_jev_none_is_unresolved(jev: JevChoiceJudge) -> None:
    route = respx.post(URL).mock(return_value=answer("none", 0.88))
    j = jev.judge(MENTION, [WORK, OTHER])
    assert j == Judgement(None, 0.88, "jev-choice", "work")
    assert route.call_count == 1


@respx.mock
def test_jev_stage_two_runs_when_the_chosen_work_has_children(jev: JevChoiceJudge) -> None:
    route = respx.post(URL).mock(side_effect=[answer("35", 0.95), answer("102", 0.8)])
    j = jev.judge(MENTION, [WORK, OTHER])
    assert route.call_count == 2
    assert j.choice is MOVEMENTS[1]
    assert j.stage == "movement"
    assert j.confidence == 0.8  # the weaker of the two stages
    second = sent(route, 1)
    assert list(second["questions"]["pick"]["criteria"]) == ["101", "102", "none"]
    assert "Etudes, Op. 10" in second["state"]


@respx.mock
def test_jev_stage_two_none_keeps_the_work(jev: JevChoiceJudge) -> None:
    respx.post(URL).mock(side_effect=[answer("35", 0.9), answer("none", 0.7)])
    assert jev.judge(MENTION, [WORK]) == Judgement(WORK, 0.9, "jev-choice", "work")


@respx.mock
def test_jev_falls_back_to_probabilities_for_confidence(jev: JevChoiceJudge) -> None:
    respx.post(URL).mock(return_value=answer("40", None, probabilities={"40": 0.77, "none": 0.2}))
    assert jev.judge(MENTION, [LEAF]).confidence == 0.77


@respx.mock
def test_jev_clamps_confidence(jev: JevChoiceJudge) -> None:
    respx.post(URL).mock(return_value=answer("40", 1.7))
    assert jev.judge(MENTION, [LEAF]).confidence == 1.0


@respx.mock
def test_jev_mixed_entity_types_get_typed_choice_names(jev: JevChoiceJudge) -> None:
    route = respx.post(URL).mock(return_value=answer("composer:7"))
    c = Candidate("composer", 7, "Chopin", 0.5)
    assert jev.judge(MENTION, [LEAF, c]).choice is c
    assert list(sent(route)["questions"]["pick"]["criteria"]) == [
        "repertoire:40",
        "composer:7",
        "none",
    ]


@respx.mock
def test_jev_composer_label_is_in_the_description(jev: JevChoiceJudge) -> None:
    route = respx.post(URL).mock(return_value=answer("40"))
    jev.judge(MENTION, [Candidate("repertoire", 40, "Nocturne", 0.8, composer_label="Chopin")])
    assert sent(route)["questions"]["pick"]["criteria"]["40"] == "Nocturne (Chopin)"


@respx.mock
def test_jev_no_candidates_makes_no_call(jev: JevChoiceJudge) -> None:
    route = respx.post(URL).mock(return_value=answer("none"))
    assert jev.judge(MENTION, []) == Judgement(None, 1.0, "jev-choice", "work")
    assert route.call_count == 0


@respx.mock
def test_jev_timeout_raises_unavailable(jev: JevChoiceJudge) -> None:
    respx.post(URL).mock(side_effect=httpx.ReadTimeout("slow"))
    with pytest.raises(JevUnavailableError):
        jev.judge(MENTION, [LEAF])


@pytest.mark.parametrize("status", [400, 401, 422, 429, 500, 503])
@respx.mock
def test_jev_http_error_raises_unavailable(jev: JevChoiceJudge, status: int) -> None:
    respx.post(URL).mock(return_value=httpx.Response(status))
    with pytest.raises(JevUnavailableError):
        jev.judge(MENTION, [LEAF])


@respx.mock
def test_jev_connection_error_raises_unavailable(jev: JevChoiceJudge) -> None:
    respx.post(URL).mock(side_effect=httpx.ConnectError("down"))
    with pytest.raises(JevUnavailableError):
        jev.judge(MENTION, [LEAF])


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, text="not json"),
        httpx.Response(200, json={"answers": {}}),
        httpx.Response(200, json={"answers": {"pick": {"choice": "999", "confidence": 0.9}}}),
    ],
)
@respx.mock
def test_jev_garbage_raises_unavailable(jev: JevChoiceJudge, response: httpx.Response) -> None:
    respx.post(URL).mock(return_value=response)
    with pytest.raises(JevUnavailableError):
        jev.judge(MENTION, [LEAF])


@respx.mock
def test_jev_missing_key_raises_before_any_request() -> None:
    route = respx.post(URL).mock(return_value=answer("40"))
    with pytest.raises(JevUnavailableError):
        JevChoiceJudge("", URL).judge(MENTION, [LEAF])
    assert route.call_count == 0


def test_jev_unavailable_is_a_judge_error() -> None:
    assert issubclass(JevUnavailableError, JudgeError)


# --- LlmJudge ---------------------------------------------------------------------------------


def llm(reply: str) -> tuple[LlmJudge, list[str]]:
    prompts: list[str] = []

    def complete(prompt: str) -> str:
        prompts.append(prompt)
        return reply

    return LlmJudge(complete, "haiku"), prompts


def test_llm_prompt_lists_a_flat_option_list_including_movements() -> None:
    j, prompts = llm('{"choice": "repertoire:35", "confidence": 0.9}')
    j.judge(MENTION, [WORK, OTHER])
    p = prompts[0]
    assert "Op. 10" in p and "Chopin" in p
    for needle in ("repertoire:35", "repertoire:36", "movement:101", "movement:102", "none"):
        assert needle in p


def test_llm_picks_a_work() -> None:
    j, _ = llm('{"choice": "repertoire:36", "confidence": 0.8}')
    assert j.judge(MENTION, [WORK, OTHER]) == Judgement(OTHER, 0.8, "haiku", "work")


def test_llm_picks_a_movement() -> None:
    j, _ = llm('{"choice": "movement:101", "confidence": 0.7}')
    assert j.judge(MENTION, [WORK, OTHER]) == Judgement(MOVEMENTS[0], 0.7, "haiku", "movement")


def test_llm_none() -> None:
    j, _ = llm('{"choice": "none", "confidence": 0.6}')
    assert j.judge(MENTION, [WORK]) == Judgement(None, 0.6, "haiku", "work")


def test_llm_tolerates_prose_and_code_fences_around_the_json() -> None:
    j, _ = llm('Sure!\n```json\n{"choice": "40", "confidence": 0.9}\n```')
    assert j.judge(MENTION, [LEAF]).choice is LEAF


@pytest.mark.parametrize(
    "reply",
    ["", "no idea", "{not json}", '{"confidence": 0.9}', '{"choice": "ghost", "confidence": 0.9}'],
)
def test_llm_malformed_output_raises_judge_error(reply: str) -> None:
    j, _ = llm(reply)
    with pytest.raises(JudgeError):
        j.judge(MENTION, [LEAF])


def test_llm_missing_confidence_is_zero() -> None:
    j, _ = llm('{"choice": "40"}')
    assert j.judge(MENTION, [LEAF]).confidence == 0.0


def test_llm_no_candidates_makes_no_call() -> None:
    j, prompts = llm("")
    assert j.judge(MENTION, []) == Judgement(None, 1.0, "haiku", "work")
    assert prompts == []


def test_llm_provider_errors_propagate() -> None:
    def boom(_: str) -> str:
        raise RuntimeError("provider down")

    with pytest.raises(RuntimeError):
        LlmJudge(boom, "haiku").judge(MENTION, [LEAF])


# --- ChainJudge -------------------------------------------------------------------------------


class Stub:
    def __init__(self, name: str, result: Judgement | Exception) -> None:
        self.name = name
        self.result = result
        self.calls = 0

    def judge(self, mention: Mention, candidates: list[Candidate]) -> Judgement:
        self.calls += 1
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def verdict(name: str, conf: float, choice: Candidate | None = LEAF) -> Judgement:
    return Judgement(choice, conf, name, "work")


def test_chain_confident_primary_does_not_escalate() -> None:
    p, e = Stub("a", verdict("a", 0.8)), Stub("b", verdict("b", 0.9))
    j = ChainJudge(p, e).judge(MENTION, [LEAF])
    assert (j, p.calls, e.calls) == (verdict("a", 0.8), 1, 0)


def test_chain_threshold_is_exclusive_at_the_boundary() -> None:
    p, e = Stub("a", verdict("a", 0.5)), Stub("b", verdict("b", 0.9))
    assert ChainJudge(p, e, threshold=0.5).judge(MENTION, [LEAF]).judge == "a"
    assert e.calls == 0


def test_chain_low_confidence_escalates_and_records_the_chain() -> None:
    p, e = (
        Stub("jev-choice", verdict("jev-choice", 0.3)),
        Stub("haiku", verdict("haiku", 0.9, OTHER)),
    )
    j = ChainJudge(p, e).judge(MENTION, [LEAF, OTHER])
    assert j == Judgement(OTHER, 0.9, "jev-choice>haiku", "work")
    assert (p.calls, e.calls) == (1, 1)


def test_chain_low_confidence_none_also_escalates() -> None:
    p, e = Stub("a", verdict("a", 0.2, None)), Stub("b", verdict("b", 0.9))
    assert ChainJudge(p, e).judge(MENTION, [LEAF]).choice is LEAF


def test_chain_escalation_result_stands_even_if_still_unsure() -> None:
    p, e = Stub("a", verdict("a", 0.2)), Stub("b", verdict("b", 0.4, None))
    assert ChainJudge(p, e).judge(MENTION, [LEAF]) == Judgement(None, 0.4, "a>b", "work")


def test_chain_low_confidence_without_escalation_returns_primary() -> None:
    p = Stub("a", verdict("a", 0.1))
    assert ChainJudge(p).judge(MENTION, [LEAF]) == verdict("a", 0.1)


def test_chain_primary_error_escalates() -> None:
    p, e = Stub("a", JevUnavailableError("down")), Stub("b", verdict("b", 0.9))
    assert ChainJudge(p, e).judge(MENTION, [LEAF]) == Judgement(LEAF, 0.9, "a>b", "work")


def test_chain_primary_error_without_escalation_raises() -> None:
    with pytest.raises(JevUnavailableError):
        ChainJudge(Stub("a", JevUnavailableError("down"))).judge(MENTION, [LEAF])


def test_chain_escalation_error_keeps_the_primary_result() -> None:
    p, e = Stub("a", verdict("a", 0.3)), Stub("b", JudgeError("garbled"))
    assert ChainJudge(p, e).judge(MENTION, [LEAF]) == verdict("a", 0.3)


def test_chain_both_failing_raises_the_escalation_error() -> None:
    p, e = Stub("a", JevUnavailableError("down")), Stub("b", JudgeError("garbled"))
    with pytest.raises(JudgeError, match="garbled"):
        ChainJudge(p, e).judge(MENTION, [LEAF])


@respx.mock
def test_jev_then_llm_end_to_end() -> None:
    respx.post(URL).mock(return_value=answer("none", 0.2))
    haiku = LlmJudge(lambda _: '{"choice": "40", "confidence": 0.85}', "haiku")
    chain = ChainJudge(JevChoiceJudge("k", URL), haiku, threshold=0.5)
    assert chain.name == "jev-choice>haiku"
    assert chain.judge(MENTION, [LEAF, OTHER]) == Judgement(LEAF, 0.85, "jev-choice>haiku", "work")
