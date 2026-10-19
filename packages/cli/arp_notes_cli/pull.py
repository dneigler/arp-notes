"""`arp-notes pull`. Owner: CLI-c ga-mxal.37. C0 stub: reports not implemented."""

from __future__ import annotations

from arp_notes_cli.registry import Subparsers, add_stub


def register(subparsers: Subparsers) -> None:
    add_stub(subparsers, "pull", "Export app notes to Markdown plus attachments.")
