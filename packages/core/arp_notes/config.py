"""HostConfig: the single typed object an integrator constructs (ADR §9.8, K§7). Owner: C1a."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from arp_notes.ports import (
    Db,
    Hooks,
    Hygiene,
    Judge,
    LinkSchemes,
    Policy,
    Principal,
    Signer,
    Storage,
)


@dataclass
class HostConfig:
    db: Db
    principal: Principal
    storage: Storage
    signer: Signer
    schemes: Sequence[LinkSchemes]
    policy: Policy
    judge: Judge | None = None
    hooks: Hooks | None = None
    hygiene: Hygiene | None = None
