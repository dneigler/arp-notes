"""`arp-notes sync`: write the `arp_id`, upload attachments first, upsert once.

Owner: CLI-b ga-mxal.36 (ADR A.4, A.5, D1).

Per note: (1) insert `arp_id` if the note has none (the only write the CLI ever makes to a vault),
(2) hash the file as it is after that write, (3) upload each attachment the host does not yet have
(`POST upload-url`, then a raw `PUT` with no Bearer), (4) `POST /notes/sync/upsert` once, and once
more if the host still reports `missing_attachments`. The host manifest decides what is new,
changed, renamed or unchanged; there is no local state file to drift out of step with it.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import tempfile
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

from arp_notes_cli import frontmatter
from arp_notes_cli.client import ClientError, NotesClient, open_client, run_command
from arp_notes_cli.config import ConfigError, add_app_argument
from arp_notes_cli.registry import Subparsers
from arp_notes_cli.scan import (
    SOURCE_SYSTEM,
    LocalNote,
    ScanRefusal,
    VaultScope,
    scan_vault_notes,
    split_frontmatter,
)
from arp_notes_cli.upload import ensure_blob, mime_for
from arp_notes_cli.verify import check_note


class NoteChanged(Exception):
    """The file changed on disk while the CLI was working on it. Nothing was overwritten."""


@dataclass
class Report:
    synced: list[dict[str, Any]] = field(default_factory=list)
    errors: list[dict[str, str]] = field(default_factory=list)
    warnings: list[dict[str, str]] = field(default_factory=list)

    def as_json(self) -> dict[str, Any]:
        out: dict[str, Any] = {"synced": self.synced, "errors": self.errors}
        if self.warnings:
            out["warnings"] = self.warnings
        return out


@dataclass
class Options:
    kind: str | None = None
    write_id: bool = True
    dry_run: bool = False
    verify: bool = False


# --- the one vault write -------------------------------------------------------------------


def write_note_atomic(path: Path, expected: bytes, new: bytes) -> None:
    """Replace `path` with `new` unless it no longer holds `expected` (Obsidian may be editing it).

    The bytes go to a dot-file beside the note and are renamed over it, so an interrupted run
    leaves the original intact. The file mode is kept. A note edited in the few milliseconds
    between the checks and the rename can still lose that edit; the checks make that window tiny.
    """
    target = path.resolve()
    if target.read_bytes() != expected:
        raise NoteChanged("the file changed while syncing; nothing was written, run sync again")
    fd, tmp_name = tempfile.mkstemp(dir=target.parent, prefix=f".{target.name}.arp-", suffix=".tmp")
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(new)
            handle.flush()
            os.fsync(handle.fileno())
        shutil.copymode(target, tmp)
        if target.read_bytes() != expected:
            raise NoteChanged("the file changed while syncing; nothing was written, run sync again")
        os.replace(tmp, target)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


# --- building the upsert -------------------------------------------------------------------


def _iso_utc(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def source_url(workspace: str, path: str) -> str:
    stem = path[:-3] if path.lower().endswith(".md") else path
    return f"obsidian://open?vault={quote(workspace, safe='')}&file={quote(stem, safe='')}"


def build_upsert(
    vault: VaultScope,
    note: LocalNote,
    data: bytes,
    doc_id: str,
    attachments: list[dict[str, Any]],
    kind: str | None,
) -> dict[str, Any]:
    """The NoteUpsert for one note. `body_md` is the whole file, frontmatter included (A.5)."""
    text = data.decode("utf-8")
    block, body = split_frontmatter(text)
    fm = frontmatter.parse_frontmatter(block)
    payload: dict[str, Any] = {
        "source_system": SOURCE_SYSTEM,
        "source_workspace": vault.root.name,
        "source_doc_id": doc_id,
        "source_path": note.path,
        "title": frontmatter.derive_title(fm, note.path),
        "body_md": text,
        "frontmatter": fm,
        "source_modified_at": _iso_utc((vault.root / note.path).stat().st_mtime),
        "source_url": source_url(vault.root.name, note.path),
        "content_hash": hashlib.sha256(data).hexdigest(),
        "attachments": [
            {
                "sha256": a["sha256"],
                "filename": Path(a["path"]).name,
                "mime": mime_for(a["path"]),
                "size_bytes": a["size_bytes"],
                "ref_in_markdown": a["ref"],
            }
            for a in attachments
        ],
    }
    chosen_kind = kind or frontmatter.guess_kind(fm, note.path)
    optional = {
        "kind": chosen_kind,
        "person": frontmatter.derive_person(fm, body),
        "note_date": frontmatter.derive_note_date(fm, note.path),
    }
    payload.update({k: v for k, v in optional.items() if v})
    return payload


# --- one session of uploads and upserts ----------------------------------------------------


class Syncer:
    def __init__(self, client: NotesClient, options: Options, caps: dict[str, Any]) -> None:
        self.client = client
        self.options = options
        self.attachments_accepted = caps.get("attachments") is not False
        self.on_host: set[str] = set()  # blobs the host is known to hold during this run
        self.report = Report()

    # -- attachments

    def _effective_attachments(self, note: LocalNote) -> list[dict[str, Any]]:
        if self.attachments_accepted or not note.attachments:
            return note.attachments
        self.report.warnings.append(
            {
                "path": note.path,
                "warning": "this host does not accept attachments: embeds are left out of the sync",
            }
        )
        return []

    def _upload(
        self, vault: VaultScope, attachments: list[dict[str, Any]], shas: list[str]
    ) -> list[str]:
        """Make sure the host holds each blob in `shas`; returns those whose bytes were PUT."""
        sent: list[str] = []
        by_sha = {a["sha256"]: a for a in attachments}
        for sha in shas:
            if sha in self.on_host:
                continue
            attachment = by_sha.get(sha)
            if attachment is None:
                raise ClientError(f"the host asks for attachment {sha}, which this note lacks")
            data = (vault.root / attachment["path"]).read_bytes()
            if hashlib.sha256(data).hexdigest() != sha:
                raise NoteChanged(f"attachment {attachment['path']} changed while syncing")
            if ensure_blob(
                self.client,
                sha256=sha,
                mime=mime_for(attachment["path"]),
                filename=Path(attachment["path"]).name,
                data=data,
            ):
                sent.append(sha)
            self.on_host.add(sha)
        return sent

    # -- upsert

    def _upsert(self, payload: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
        """POST the upsert; returns (result, shas the host reported missing)."""
        try:
            result = self.client.request("POST", "/notes/sync/upsert", json=payload)
        except ClientError as exc:
            body = exc.body
            if exc.status == 409 and isinstance(body, dict) and body.get("error") == "blob_missing":
                return {}, list(body.get("missing") or [])
            raise
        if not isinstance(result, dict) or "note_id" not in result:
            raise ClientError("upsert answer has no note_id")
        return result, list(result.get("missing_attachments") or [])

    # -- one note

    def sync_note(
        self,
        vault: VaultScope,
        note: LocalNote,
        row: dict[str, Any] | None,
        duplicated: bool,
    ) -> None:
        opts = self.options
        if duplicated:
            self.report.errors.append(
                {"path": note.path, "error": f"duplicate arp_id {note.arp_id} (a copied note?)"}
            )
            return
        file = vault.root / note.path
        raw = file.read_bytes()
        if hashlib.sha256(raw).hexdigest() != note.content_hash:
            raise NoteChanged("the file changed after it was scanned; run sync again")

        attachments = self._effective_attachments(note)
        needs_id = not note.arp_id

        if opts.dry_run:
            self._dry_run_note(vault, note, row, attachments, needs_id)
            return

        doc_id = note.arp_id
        data = raw
        if needs_id and opts.write_id:
            data, doc_id, _ = frontmatter.ensure_arp_id(raw, str(uuid.uuid4()))
            write_note_atomic(file, raw, data)
        elif needs_id:
            doc_id = note.path
            self.report.warnings.append(
                {
                    "path": note.path,
                    "warning": (
                        "synced with its path as identity (--no-write-id): renaming or moving "
                        "this note will make the host treat it as a new note"
                    ),
                }
            )
        assert doc_id is not None

        known = set(row["attachments"]) if row and row["source_doc_id"] == doc_id else set()
        wanted = list(dict.fromkeys(a["sha256"] for a in attachments))
        uploaded = self._upload(vault, attachments, [s for s in wanted if s not in known])

        payload = build_upsert(vault, note, data, doc_id, attachments, opts.kind)
        result, missing = self._upsert(payload)
        if missing:  # A.4 step 3: upload what the host lacks, then re-upsert once
            self.on_host.difference_update(missing)
            uploaded += self._upload(vault, attachments, missing)
            result, missing = self._upsert(payload)
            if missing:
                raise ClientError(f"the host still lacks attachments after upload: {missing}")

        item: dict[str, Any] = {
            "path": note.path,
            "workspace": vault.root.name,
            "note_id": result["note_id"],
            "outcome": result.get("outcome"),
            "uploaded": uploaded,
        }
        if row and row["source_path"] != note.path:
            item["renamed_from"] = row["source_path"]
        if note.unresolved_embeds:
            item["unresolved_embeds"] = note.unresolved_embeds
        self.report.synced.append(item)

        if opts.verify:
            host_note = self.client.request("GET", f"/notes/{result['note_id']}")
            problems = check_note(host_note, data, doc_id)
            item["verified"] = not problems
            if problems:
                self.report.errors.append({"path": note.path, "error": "; ".join(problems)})

    def _dry_run_note(
        self,
        vault: VaultScope,
        note: LocalNote,
        row: dict[str, Any] | None,
        attachments: list[dict[str, Any]],
        needs_id: bool,
    ) -> None:
        wanted = {a["sha256"] for a in attachments}
        if row is None:
            outcome = "would_create"
            would_upload = sorted(wanted)
        else:
            known = set(row["attachments"])
            changed = (
                row["content_hash"] != note.content_hash
                or row["source_path"] != note.path
                or known != wanted
                or bool(row.get("deleted_at"))
            )
            outcome = "would_update" if changed else "unchanged"
            would_upload = sorted(wanted - known)
        item: dict[str, Any] = {
            "path": note.path,
            "workspace": vault.root.name,
            "note_id": None,
            "outcome": outcome,
            "uploaded": [],
            "would_upload": would_upload,
        }
        if needs_id and self.options.write_id:
            item["would_write_id"] = True
        if row and row["source_path"] != note.path:
            item["renamed_from"] = row["source_path"]
        self.report.synced.append(item)

    # -- whole run

    def run(self, vaults: list[VaultScope], scan_errors: list[dict[str, str]]) -> Report:
        self.report.errors.extend(scan_errors)
        aborted: str | None = None
        for vault in vaults:
            rows = {
                row["source_doc_id"]: row
                for row in self.client.manifest(SOURCE_SYSTEM, vault.root.name)
            }
            counts: dict[str, int] = {}
            for note in vault.notes:
                if note.arp_id:
                    counts[note.arp_id] = counts.get(note.arp_id, 0) + 1
            for note in sorted(vault.notes, key=lambda n: n.path):
                if aborted:
                    self.report.errors.append(
                        {"path": note.path, "error": f"not attempted: {aborted}"}
                    )
                    continue
                identity = note.arp_id or (note.path if not self.options.write_id else None)
                try:
                    self.sync_note(
                        vault,
                        note,
                        rows.get(identity) if identity else None,
                        bool(note.arp_id and counts[note.arp_id] > 1),
                    )
                except ClientError as exc:
                    self.report.errors.append({"path": note.path, "error": str(exc)})
                    if exc.status is None or exc.status in (401, 403):
                        aborted = str(exc)
                except (NoteChanged, frontmatter.FrontmatterError) as exc:
                    self.report.errors.append({"path": note.path, "error": str(exc)})
                except OSError as exc:
                    self.report.errors.append(
                        {"path": note.path, "error": f"file error: {exc.strerror or exc}"}
                    )
        return self.report


# --- command -------------------------------------------------------------------------------


def _print_human(report: Report, options: Options) -> None:
    for item in report.synced:
        extra = f", {len(item['uploaded'])} uploaded" if item["uploaded"] else ""
        if options.dry_run and item.get("would_upload"):
            extra = f", would upload {len(item['would_upload'])}"
        ident = "" if item["note_id"] is None else f" (note {item['note_id']}{extra})"
        print(f"{item['outcome']}  {item['path']}{ident}")
    for warning in report.warnings:
        print(f"warning: {warning['path']}: {warning['warning']}", file=sys.stderr)
    for error in report.errors:
        print(f"error: {error['path']}: {error['error']}", file=sys.stderr)


def _cmd_sync(args: argparse.Namespace) -> int:
    options = Options(
        kind=args.kind, write_id=not args.no_write_id, dry_run=args.dry_run, verify=args.verify
    )

    def body() -> int:
        try:  # judge the paths first: a refusal needs no app, token or network
            vaults, scan_errors = scan_vault_notes([Path(p) for p in args.paths])
        except ScanRefusal as exc:
            raise ConfigError(str(exc)) from exc
        with open_client(args.app) as client:
            caps = client.capabilities()
            report = Syncer(client, options, caps).run(vaults, scan_errors)
        if args.json:
            print(json.dumps(report.as_json(), indent=2, ensure_ascii=False))
        else:
            _print_human(report, options)
        return 1 if report.errors else 0

    return run_command("sync", body)


def register(subparsers: Subparsers) -> None:
    parser = subparsers.add_parser(
        "sync",
        help="Upload attachments and upsert notes.",
        description=(
            "Sync explicit Obsidian files/folders to the host. A note without an arp_id gets one "
            "line, `arp_id: <uuid>`, inserted into its frontmatter (the only write to your vault); "
            "attachments are uploaded first, then the note is upserted. Prints "
            "{synced, errors}; exits non-zero if any note failed."
        ),
    )
    parser.add_argument("paths", nargs="+", help="Markdown files or folders inside a vault")
    add_app_argument(parser)
    parser.add_argument("--dry-run", action="store_true", help="make no writes, local or remote")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument(
        "--no-write-id",
        action="store_true",
        help="do not touch the vault: identify notes without an arp_id by path (a rename then "
        "looks like a new note)",
    )
    parser.add_argument("--kind", help="note kind for every note in this run (default: guessed)")
    parser.add_argument(
        "--verify",
        action="store_true",
        help="after syncing, download each note and compare content_hash and body bytes",
    )
    parser.set_defaults(func=_cmd_sync)
