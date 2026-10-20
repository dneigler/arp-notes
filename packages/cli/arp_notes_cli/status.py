"""`arp-notes status`: the last sync per path, read from the server manifest.

Owner: CLI-a ga-mxal.6 (ADR A.5). The server manifest is the truth; no local state is consulted.
"""

from __future__ import annotations

import argparse
import json
from typing import Any

from arp_notes_cli.client import NotesClient, open_client, run_command
from arp_notes_cli.config import add_app_argument
from arp_notes_cli.registry import Subparsers


def collect_status(
    client: NotesClient, workspaces: list[str], source_system: str
) -> list[dict[str, Any]]:
    """One entry per (source_system, workspace): its manifest rows, sorted by path.

    With no `workspaces`, every source the host reports in `sync_sources` (K§2) is shown.
    """
    if workspaces:
        sources = [{"source_system": source_system, "source_workspace": w} for w in workspaces]
    else:
        sources = client.sync_sources()
    report: list[dict[str, Any]] = []
    for source in sources:
        system, workspace = source["source_system"], source["source_workspace"]
        rows = client.manifest(system, workspace)
        notes = [
            {
                "path": row["source_path"],
                "arp_id": row["source_doc_id"],
                "last_synced_at": row["last_synced_at"],
                "deleted_at": row.get("deleted_at"),
            }
            for row in sorted(rows, key=lambda r: r["source_path"])
        ]
        report.append({"source_system": system, "source_workspace": workspace, "notes": notes})
    return report


def _cmd_status(args: argparse.Namespace) -> int:
    def body() -> int:
        with open_client(args.app) as client:
            report = collect_status(client, args.workspace, args.source_system)
        if args.json:
            print(json.dumps({"sources": report}, indent=2, ensure_ascii=False))
            return 0
        if not report:
            print("nothing synced yet")
        for source in report:
            notes = source["notes"]
            print(f"{source['source_system']} “{source['source_workspace']}” ({len(notes)} notes)")
            for note in notes:
                state = f"source deleted {note['deleted_at']}" if note["deleted_at"] else "synced"
                print(f"  {note['path']}  {state}  last sync {note['last_synced_at']}")
        return 0

    return run_command("status", body)


def register(subparsers: Subparsers) -> None:
    parser = subparsers.add_parser(
        "status",
        help="Show the last sync per path from the manifest.",
        description="Show the last sync of every path the host holds, per source workspace.",
    )
    add_app_argument(parser)
    parser.add_argument(
        "--workspace",
        action="append",
        default=[],
        metavar="NAME",
        help="vault name to report (repeatable; default: every source the host lists)",
    )
    parser.add_argument(
        "--source-system", default="obsidian", help="source system for --workspace (obsidian)"
    )
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.set_defaults(func=_cmd_status)
