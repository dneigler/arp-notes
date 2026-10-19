"""`arp-notes sync`. Owner: CLI-b ga-mxal.36. C0 stub: reports not implemented."""

from __future__ import annotations

from arp_notes_cli.registry import Subparsers, add_stub


def register(subparsers: Subparsers) -> None:
    add_stub(subparsers, "sync", "Upload attachments and upsert notes.")
