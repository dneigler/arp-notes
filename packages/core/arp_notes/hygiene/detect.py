"""Core hygiene detectors (K§6.2). Owner: H1a (ga-mxal.30)."""

from __future__ import annotations

from arp_notes.config import HostConfig
from arp_notes.models import HygieneIssue


def detect(cfg: HostConfig, user_id: str, scope: str = "all") -> list[HygieneIssue]:
    raise NotImplementedError("H1a: hygiene.detect.detect")
