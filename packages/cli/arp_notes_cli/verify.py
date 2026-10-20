"""`arp-notes verify`: prove the host holds the local bytes, not a paraphrase.

Owner: CLI-b ga-mxal.36 (--conformance: C7b ga-mxal.38).

A.4 step 4: `GET /notes/{id}` must return a `content_hash` equal to the SHA-256 of the local file,
and a `body_md` whose UTF-8 bytes equal the file. `sync --verify` calls `check_note` with the id the
upsert just returned; the standalone command has only an `arp_id`, so it first finds the note id
(`find_note_ids`).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

from arp_notes_cli.client import ClientError, NotesClient, open_client, run_command
from arp_notes_cli.config import ConfigError, add_app_argument
from arp_notes_cli.conformance_cmd import add_options, run_conformance
from arp_notes_cli.registry import Subparsers
from arp_notes_cli.scan import SOURCE_SYSTEM, ScanRefusal, scan_vault_notes

LIST_PAGE_LIMIT = 100  # A.2: limit 1..100


def first_difference(host: bytes, local: bytes) -> int:
    """Index of the first byte where the two differ (the shorter length if one is a prefix)."""
    for index, (a, b) in enumerate(zip(host, local, strict=False)):
        if a != b:
            return index
    return min(len(host), len(local))


def check_note(note: Any, local: bytes, arp_id: str | None) -> list[str]:
    """Problems found comparing a `GET /notes/{id}` answer with the local file; empty = verified."""
    if not isinstance(note, dict):
        return ["the host did not return a note"]
    problems: list[str] = []
    expected_hash = hashlib.sha256(local).hexdigest()
    if note.get("content_hash") != expected_hash:
        problems.append(
            f"content_hash mismatch: host has {note.get('content_hash')}, local file is "
            f"{expected_hash}"
        )
    body = note.get("body_md")
    if not isinstance(body, str):
        problems.append("the host note has no body_md")
    else:
        host_bytes = body.encode("utf-8")
        if host_bytes != local:
            problems.append(
                f"body differs from the local file at byte {first_difference(host_bytes, local)} "
                f"(host {len(host_bytes)} bytes, local {len(local)} bytes)"
            )
    doc_id = note.get("source_doc_id")
    if arp_id and doc_id is not None and doc_id != arp_id:
        problems.append(f"the host note belongs to source_doc_id {doc_id}, not {arp_id}")
    return problems


def find_note_ids(
    client: NotesClient, source_system: str, workspace: str
) -> dict[str, tuple[int, bool]]:
    """`source_path` -> (note id, tombstoned) for one workspace, paging through GET /notes.

    The manifest does not carry note ids, so the standalone verify matches a note's manifest path
    against the list rows' `source_workspace` and `source_path`. `check_note` then confirms the
    note's `source_doc_id`, so a path collision cannot pass as a match.
    """
    found: dict[str, tuple[int, bool]] = {}
    cursor: str | None = None
    while True:
        page = client.request(
            "GET",
            "/notes",
            params={
                "source_system": source_system,
                "include_deleted": "true",
                "limit": LIST_PAGE_LIMIT,
                "before": cursor,
            },
        )
        if not isinstance(page, dict) or not isinstance(page.get("items"), list):
            raise ClientError("GET /notes returned no `items` list")
        for item in page["items"]:
            if item.get("source_workspace") == workspace and item.get("source_path"):
                found[item["source_path"]] = (item["id"], bool(item.get("deleted_at")))
        next_cursor = page.get("next_cursor")
        if not next_cursor:
            return found
        if next_cursor == cursor:
            raise ClientError("GET /notes paging does not advance (next_cursor repeats)")
        cursor = next_cursor


def verify_paths(
    client: NotesClient, paths: list[Path]
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """Verify explicit files/folders against the host. Reads only; writes nothing."""
    try:
        vaults, errors = scan_vault_notes(paths)
    except ScanRefusal as exc:
        raise ConfigError(str(exc)) from exc
    verified: list[dict[str, Any]] = []
    errors = list(errors)
    for vault in vaults:
        manifest = {
            row["source_doc_id"]: row for row in client.manifest(SOURCE_SYSTEM, vault.root.name)
        }
        ids: dict[str, tuple[int, bool]] | None = None
        for note in vault.notes:
            if not note.arp_id:
                errors.append({"path": note.path, "error": "no arp_id: this note was never synced"})
                continue
            row = manifest.get(note.arp_id)
            if row is None:
                errors.append({"path": note.path, "error": "the host has no note with this arp_id"})
                continue
            if ids is None:
                ids = find_note_ids(client, SOURCE_SYSTEM, vault.root.name)
            located = ids.get(row["source_path"])
            if located is None:
                errors.append(
                    {
                        "path": note.path,
                        "error": f"cannot find the host note for {row['source_path']}",
                    }
                )
                continue
            try:
                local = (vault.root / note.path).read_bytes()
                host_note = client.request("GET", f"/notes/{located[0]}")
            except OSError as exc:
                errors.append({"path": note.path, "error": f"unreadable: {exc.strerror or exc}"})
                continue
            except ClientError as exc:
                errors.append({"path": note.path, "error": str(exc)})
                continue
            problems = check_note(host_note, local, note.arp_id)
            if problems:
                errors.append({"path": note.path, "error": "; ".join(problems)})
            else:
                verified.append(
                    {
                        "path": note.path,
                        "note_id": located[0],
                        "content_hash": hashlib.sha256(local).hexdigest(),
                    }
                )
    return verified, errors


def _cmd_verify(args: argparse.Namespace) -> int:
    def body() -> int:
        if args.conformance:  # C7b: the kit against the live host, no local files involved
            if args.paths:
                raise ConfigError("--conformance takes no paths: it checks the host, not files")
            return run_conformance(
                args.app,
                only=args.only,
                fixture=args.fixture,
                schemas=args.schemas,
                mcp_url=args.mcp_url,
                as_json=args.json,
            )
        if not args.paths:
            raise ConfigError("verify needs Markdown files or folders (or --conformance)")
        with open_client(args.app) as client:
            verified, errors = verify_paths(client, [Path(p) for p in args.paths])
        if args.json:
            print(
                json.dumps({"verified": verified, "errors": errors}, indent=2, ensure_ascii=False)
            )
        else:
            for item in verified:
                print(f"verified  {item['path']}  note {item['note_id']}")
            for error in errors:
                print(f"error: {error['path']}: {error['error']}", file=sys.stderr)
        return 1 if errors else 0

    return run_command("verify", body)


def register(subparsers: Subparsers) -> None:
    parser = subparsers.add_parser(
        "verify",
        help="Verify synced notes byte-for-byte.",
        description=(
            "Download each note from the host and check that its content_hash and body bytes "
            "equal the local file. Reads only; exits non-zero on any mismatch. With "
            "--conformance, run the conformance kit against the live host (see "
            "`arp-notes conformance`)."
        ),
    )
    parser.add_argument("paths", nargs="*", help="Markdown files or folders inside a vault")
    add_app_argument(parser)
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument(
        "--conformance",
        action="store_true",
        help="run the conformance kit against the live host instead of verifying files",
    )
    add_options(parser)
    parser.set_defaults(func=_cmd_verify)
