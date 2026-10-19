"""`arp-notes verify`. C0 stub: reports not implemented.

Owner: CLI-b ga-mxal.36 (--conformance: C7b ga-mxal.38).
"""

from __future__ import annotations

from arp_notes_cli.registry import Subparsers, add_stub


def register(subparsers: Subparsers) -> None:
    add_stub(subparsers, "verify", "Verify synced notes byte-for-byte.")
