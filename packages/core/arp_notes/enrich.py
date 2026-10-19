"""Resolver pipeline: tokenise -> candidates -> duplicate collapse -> judge -> escalate (K§4).

Owner: C5a (ga-mxal.12).
"""

from __future__ import annotations

from arp_notes.config import HostConfig
from arp_notes.models import Proposal
from arp_notes.ports import Span

__all__ = ["Span", "propose", "tokenise"]


def tokenise(body_md: str) -> list[Span]:
    raise NotImplementedError("C5a: enrich.tokenise")


def propose(
    cfg: HostConfig, user_id: str, note_id: int, *, llm: bool = False, refresh: bool = False
) -> Proposal:
    raise NotImplementedError("C5a: enrich.propose")
