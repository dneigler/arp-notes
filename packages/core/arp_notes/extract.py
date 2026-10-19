"""Layer 2 extraction: takeaways and action items. Owner: C5b (ga-mxal.27).

Needs policy.llm_enrich and hooks.llm_complete; the core imports no provider SDK.

The host injects `hooks.llm_complete(prompt) -> text` and picks the model. The prompt template
ships in the package (`prompts/extract.md`). Model output is untrusted: it is parsed and validated
here, and anything that does not validate is dropped, so a bad answer costs an empty result and a
warning, never an exception into `propose`.
"""

from __future__ import annotations

import json
import logging
import re
from importlib import resources
from string import Template
from typing import Any

from arp_notes.anchors import slug
from arp_notes.config import HostConfig
from arp_notes.models import Note, Proposal, ProposedAction

__all__ = ["LlmDisabled", "extract", "merge"]

log = logging.getLogger(__name__)

PROPOSED_BY = "llm"
MAX_BODY_CHARS = 40_000  # the prompt carries the note body; a longer note is cut, not refused
MAX_ITEMS = 8  # per list; mirrors the prompt
MAX_TEXT_CHARS = 280

_HEADING = re.compile(r"^#{1,6}[ \t]+(.+?)[ \t#]*$", re.MULTILINE)
_BLOCK_ID = re.compile(r"(?:^|\s)(\^[A-Za-z0-9-]+)\s*$", re.MULTILINE)
_LANES = ("practice", "lesson")


class LlmDisabled(Exception):
    """Layer 2 is off: policy.llm_enrich is false or hooks.llm_complete is missing.

    C3 maps it to 503 {"error": "llm_disabled"}.
    """


def _template() -> Template:
    return Template(resources.files("arp_notes").joinpath("prompts/extract.md").read_text("utf-8"))


def _anchors(body_md: str) -> list[str]:
    found = [slug(m.group(1)) for m in _HEADING.finditer(body_md)]
    found += _BLOCK_ID.findall(body_md)
    return list(dict.fromkeys(a for a in found if a))


def _entity_key(entity_type: str, entity_id: int) -> str:
    return f"{entity_type}:{entity_id}"


def _entities(proposal: Proposal) -> dict[str, tuple[str, int]]:
    """Entity ids offered to the model -> (entity_type, entity_id), from the resolver's links."""
    return {
        _entity_key(link.entity_type, link.entity_id): (link.entity_type, link.entity_id)
        for link in proposal.links
    }


def _prompt(note: Note, proposal: Proposal, anchors: list[str]) -> str:
    entities = [
        f"- {_entity_key(link.entity_type, link.entity_id)}: {link.entity_label}"
        for link in proposal.links
    ]
    return _template().substitute(
        title=note.title,
        kind=note.kind,
        entities="\n".join(dict.fromkeys(entities)) or "(none)",
        anchors="\n".join(f"- {a}" for a in anchors) or "(none)",
        body=note.body_md[:MAX_BODY_CHARS],
    )


def _parse(text: str) -> dict[str, Any]:
    found = re.search(r"\{.*\}", text, re.DOTALL)
    if found is None:
        raise ValueError("no JSON object")
    data = json.loads(found.group(0))
    if not isinstance(data, dict):
        raise ValueError("not a JSON object")
    return data


def _clean(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    value = " ".join(value.split())[:MAX_TEXT_CHARS]
    return value or None


def _anchor(value: Any, anchors: list[str]) -> str | None:
    return value if isinstance(value, str) and value in anchors else None


def _items(data: dict[str, Any], key: str) -> list[dict[str, Any]]:
    raw = data.get(key)
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ValueError(f"{key} is not a list")
    return [r for r in raw if isinstance(r, dict)][:MAX_ITEMS]


def _validate(
    data: dict[str, Any], anchors: list[str], entities: dict[str, tuple[str, int]]
) -> dict[str, Any]:
    takeaways = []
    for raw in _items(data, "takeaways"):
        comment = _clean(raw.get("comment"))
        if comment:
            takeaways.append({"anchor": _anchor(raw.get("anchor"), anchors), "comment": comment})
    actions: list[ProposedAction] = []
    for raw in _items(data, "action_items"):
        text = _clean(raw.get("text"))
        lane = raw.get("lane")
        if not text or lane not in _LANES:
            continue
        ref = raw.get("entity")
        entity = entities.get(ref) if isinstance(ref, str) else None
        actions.append(
            ProposedAction(
                text=text,
                anchor=_anchor(raw.get("anchor"), anchors),
                entity_type=entity[0] if entity else None,
                entity_id=entity[1] if entity else None,
                lane=lane,
                proposed_by=PROPOSED_BY,
            )
        )
    return {"takeaways": takeaways, "action_items": actions}


def extract(cfg: HostConfig, note: Note, proposal: Proposal) -> dict[str, Any]:
    """-> {takeaways: [{anchor, comment}], action_items: [ProposedAction]}

    Raises LlmDisabled when policy.llm_enrich is false or hooks.llm_complete is missing. A failing
    or malformed model answer gives an empty result and a logged warning; it never raises.
    """
    complete = cfg.hooks.llm_complete if cfg.hooks else None
    if not cfg.policy.llm_enrich or complete is None:
        raise LlmDisabled("llm_enrich is off or hooks.llm_complete is not set")
    anchors = _anchors(note.body_md)
    empty: dict[str, Any] = {"takeaways": [], "action_items": []}
    try:
        text = complete(_prompt(note, proposal, anchors))
        return _validate(_parse(text), anchors, _entities(proposal))
    except Exception as exc:  # the provider call and the model's output are both untrusted
        log.warning("extract: note %s: no usable LLM output: %r", note.id, exc)
        return empty


def merge(proposal: Proposal, result: dict[str, Any]) -> Proposal:
    """Fold an `extract` result into a Proposal (what `propose(llm=True)` returns).

    `Proposal.takeaways` is a list of strings on the wire (ADR A.2), so each takeaway's comment is
    kept and its anchor stays with the confirm step. Duplicates of resolver output are skipped.
    """
    seen = {(a.text.lower(), a.lane) for a in proposal.action_items}
    actions = [a for a in result["action_items"] if (a.text.lower(), a.lane) not in seen]
    comments = [t["comment"] for t in result["takeaways"] if t["comment"] not in proposal.takeaways]
    generated_by = list(dict.fromkeys([*proposal.generated_by, "llm"]))
    return proposal.model_copy(
        update={
            "action_items": [*proposal.action_items, *actions],
            "takeaways": [*proposal.takeaways, *comments],
            "generated_by": generated_by,
        }
    )
