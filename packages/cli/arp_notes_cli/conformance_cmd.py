"""`arp-notes conformance`. Owner: C7b ga-mxal.38. C0 stub: reports not implemented."""

from __future__ import annotations

from arp_notes_cli.registry import Subparsers, add_stub


def register(subparsers: Subparsers) -> None:
    add_stub(subparsers, "conformance", "Run the conformance kit against a live host.")
