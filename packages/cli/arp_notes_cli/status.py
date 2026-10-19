"""`arp-notes status`. Owner: CLI-a ga-mxal.6. C0 stub: reports not implemented."""

from __future__ import annotations

from arp_notes_cli.registry import Subparsers, add_stub


def register(subparsers: Subparsers) -> None:
    add_stub(subparsers, "status", "Show the last sync per path from the manifest.")
