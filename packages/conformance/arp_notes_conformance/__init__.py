"""arp-notes conformance kit. Owners: C7a (ga-mxal.14) for harness + suite_core, C7b (ga-mxal.38)
for the rest. C0 stub."""

from __future__ import annotations

from typing import Any


def suite(
    *,
    app: Any = None,
    base_url: str | None = None,
    token: str | None = None,
    fixture: Any = None,
) -> None:
    """Run the kit against an ASGI `app` or a `base_url` (exactly one)."""
    raise NotImplementedError("C7a: arp_notes_conformance.suite")
