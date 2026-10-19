"""Resolver pipeline: tokenise -> candidates -> duplicate collapse -> judge -> escalate (K§4).

Owner: C5a (ga-mxal.12).
"""

from __future__ import annotations

from dataclasses import dataclass

from arp_notes.config import HostConfig
from arp_notes.models import Proposal


@dataclass
class Span:
    """A tokenised mention with carried context. C5a owns the fields."""


def tokenise(body_md: str) -> list[Span]:
    raise NotImplementedError("C5a: enrich.tokenise")


def propose(
    cfg: HostConfig, user_id: str, note_id: int, *, llm: bool = False, refresh: bool = False
) -> Proposal:
    raise NotImplementedError("C5a: enrich.propose")
