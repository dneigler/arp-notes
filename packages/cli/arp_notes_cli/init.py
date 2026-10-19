"""`arp-notes init`. Owner: C9 ga-mxal.23. C0 stub: reports not implemented."""

from __future__ import annotations

from arp_notes_cli.registry import Subparsers, add_stub


def register(subparsers: Subparsers) -> None:
    add_stub(subparsers, "init", "Scaffold an arp-notes integration into a host app.")
