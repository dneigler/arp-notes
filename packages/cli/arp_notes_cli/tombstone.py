"""`arp-notes tombstone`: mark notes whose source was deleted.

Owner: CLI-b ga-mxal.36 (ADR A.5, §3.2).

`POST /notes/sync/tombstone` is keyed by (source_system, source_workspace, source_doc_ids), but the
command line only has `arp_id`s. Without `--workspace`, each id is looked up in the manifests of
the sources the host reports (`sync_sources`, K§2), and ids found nowhere are reported as unknown
without being sent. The host keeps the body; it only hides the note from feeds.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from typing import Any

from arp_notes_cli.client import NotesClient, open_client, run_command
from arp_notes_cli.config import add_app_argument
from arp_notes_cli.registry import Subparsers


def locate(
    client: NotesClient, arp_ids: list[str]
) -> tuple[dict[tuple[str, str], list[str]], list[str]]:
    """Group `arp_ids` by the (source_system, source_workspace) whose manifest holds them."""
    remaining = set(arp_ids)
    grouped: dict[tuple[str, str], list[str]] = defaultdict(list)
    for source in client.sync_sources():
        if not remaining:
            break
        key = (source["source_system"], source["source_workspace"])
        for row in client.manifest(*key):
            if row["source_doc_id"] in remaining:
                grouped[key].append(row["source_doc_id"])
                remaining.discard(row["source_doc_id"])
    return grouped, [i for i in arp_ids if i in remaining]


def tombstone(
    client: NotesClient, arp_ids: list[str], *, source_system: str, workspaces: list[str]
) -> dict[str, Any]:
    """Tombstone `arp_ids`; returns the combined {tombstoned, unknown} of every call made."""
    ids = list(dict.fromkeys(arp_ids))  # same id twice is one request
    unknown: list[str] = []
    if workspaces:
        groups = {(source_system, w): ids for w in workspaces}
    else:
        groups, unknown = locate(client, ids)
    tombstoned = 0
    for (system, workspace), doc_ids in groups.items():
        answer = client.request(
            "POST",
            "/notes/sync/tombstone",
            json={
                "source_system": system,
                "source_workspace": workspace,
                "source_doc_ids": doc_ids,
            },
        )
        tombstoned += int(answer.get("tombstoned", 0))
        unknown.extend(answer.get("unknown") or [])
    if len(workspaces) > 1:  # an id is unknown only if every workspace said so
        unknown = [i for i in dict.fromkeys(unknown) if unknown.count(i) == len(workspaces)]
    return {"tombstoned": tombstoned, "unknown": unknown}


def _cmd_tombstone(args: argparse.Namespace) -> int:
    def body() -> int:
        with open_client(args.app) as client:
            result = tombstone(
                client,
                args.arp_ids,
                source_system=args.source_system,
                workspaces=args.workspace,
            )
        if args.json:
            print(json.dumps(result, indent=2, ensure_ascii=False))
        else:
            print(f"tombstoned {result['tombstoned']}")
            for arp_id in result["unknown"]:
                print(f"error: unknown arp_id {arp_id}", file=sys.stderr)
        return 1 if result["unknown"] else 0

    return run_command("tombstone", body)


def register(subparsers: Subparsers) -> None:
    parser = subparsers.add_parser(
        "tombstone",
        help="Tombstone notes by arp_id.",
        description=(
            "Tell the host that the source of these notes was deleted. The host keeps the body "
            "and hides the note from feeds. Exits 1 if any arp_id is unknown to the host."
        ),
    )
    parser.add_argument("arp_ids", nargs="+", metavar="arp_id", help="arp_id of a synced note")
    add_app_argument(parser)
    parser.add_argument(
        "--workspace",
        action="append",
        default=[],
        metavar="NAME",
        help="vault the ids belong to (repeatable; default: found through the manifests)",
    )
    parser.add_argument(
        "--source-system", default="obsidian", help="source system for --workspace (obsidian)"
    )
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.set_defaults(func=_cmd_tombstone)
