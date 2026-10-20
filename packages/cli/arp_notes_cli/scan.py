"""`arp-notes scan`: diff explicit files/folders against the server manifest. No writes.

Owner: CLI-a ga-mxal.6 (ADR A.5, D1, D2).

Scan reads local files and one server manifest per vault; it changes nothing on either side. The
sync lane (CLI-b) reuses `scan_vault_notes` for the same per-note facts.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import unquote

from arp_notes_cli.client import NotesClient, open_client, run_command
from arp_notes_cli.config import ConfigError, add_app_argument
from arp_notes_cli.registry import Subparsers

SOURCE_SYSTEM = "obsidian"

# What Obsidian renders as an embed. Anything else (`![[Other note]]`, `![[data.csv]]`) is not an
# attachment this protocol moves.
ATTACHMENT_EXTENSIONS = frozenset(
    {
        # images
        ".avif", ".bmp", ".gif", ".jpeg", ".jpg", ".png", ".svg", ".webp",
        # audio
        ".flac", ".m4a", ".mp3", ".ogg", ".wav", ".3gp",
        # video
        ".mkv", ".mov", ".mp4", ".ogv", ".webm",
        # documents
        ".pdf",
    }
)  # fmt: skip

_WIKI_EMBED = re.compile(r"!\[\[([^\]\n]+)\]\]")
_MD_IMAGE = re.compile(r"!\[[^\]\n]*\]\(\s*(<[^>\n]+>|[^)\s]+)(?:\s+\"[^\"\n]*\")?\s*\)")
_INLINE_CODE = re.compile(r"`[^`\n]*`")
_ARP_ID_LINE = re.compile(r"^arp_id[ \t]*:[ \t]*(.*?)[ \t]*$")
_URL_SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")


class ScanRefusal(Exception):
    """Input the scan will not process (a vault root, a path outside any vault). Exit code 2."""


# --- frontmatter (read only) ---------------------------------------------------------------


def split_frontmatter(text: str) -> tuple[str | None, str]:
    """Return (frontmatter block without its fences, body). `None` when there is no block.

    A block is a first line of `---` and the next line that is `---` or `...`. Nothing here parses
    YAML: keys with spaces, dataview inline fields and Templater expressions pass through.
    """
    lines = text.lstrip("﻿").splitlines(keepends=True)
    if not lines or lines[0].rstrip("\r\n") != "---":
        return None, text
    for index in range(1, len(lines)):
        if lines[index].rstrip("\r\n") in ("---", "..."):
            return "".join(lines[1:index]), "".join(lines[index + 1 :])
    return None, text


def read_arp_id(text: str) -> str | None:
    """The note's `arp_id` (D1) if its frontmatter has one. Never writes."""
    block, _ = split_frontmatter(text)
    if block is None:
        return None
    for line in block.splitlines():
        match = _ARP_ID_LINE.match(line)
        if match:
            value = match.group(1)
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            return value.strip() or None
    return None


# --- vaults --------------------------------------------------------------------------------


def is_vault_root(path: Path) -> bool:
    return path.is_dir() and (path / ".obsidian").is_dir()


def find_vault_root(path: Path) -> Path | None:
    """Nearest ancestor of `path` (a file, or a folder inside the vault) holding `.obsidian/`."""
    for candidate in path.parents:
        if is_vault_root(candidate):
            return candidate
    return None


def _walk(root: Path) -> list[Path]:
    """Every file under `root`, skipping dot-folders (.obsidian, .git, .trash) like Obsidian."""
    found: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
        found.extend(Path(dirpath) / name for name in sorted(filenames))
    return found


class AttachmentIndex:
    """Vault files that can be embedded, resolved by Obsidian's rule: by filename anywhere in the
    vault, shortest path wins (an exact-case match beats a case-insensitive one)."""

    def __init__(self, vault_root: Path) -> None:
        self.root = vault_root
        self._by_name: dict[str, list[PurePosixPath]] = defaultdict(list)
        for file in _walk(vault_root):
            if file.suffix.lower() in ATTACHMENT_EXTENSIONS:
                rel = PurePosixPath(file.relative_to(vault_root).as_posix())
                self._by_name[rel.name.lower()].append(rel)

    @staticmethod
    def _rank(rel: PurePosixPath, target: PurePosixPath) -> tuple[int, int, int, str]:
        exact = rel.name == target.name
        return (0 if exact else 1, len(rel.parts), len(str(rel)), str(rel))

    def by_name(self, target: str) -> PurePosixPath | None:
        wanted = PurePosixPath(target.strip("/"))
        if not wanted.name:
            return None
        suffix = [part.lower() for part in wanted.parts]
        matches = [
            rel
            for rel in self._by_name.get(wanted.name.lower(), [])
            if [p.lower() for p in rel.parts[-len(suffix) :]] == suffix
        ]
        return min(matches, key=lambda rel: self._rank(rel, wanted), default=None)

    def exists(self, rel: PurePosixPath) -> bool:
        return rel in self._by_name.get(rel.name.lower(), [])

    def resolve_markdown_link(self, note_rel: PurePosixPath, target: str) -> PurePosixPath | None:
        """Standard `![alt](path)`: relative to the note, then to the vault root, then by name."""
        decoded = unquote(target)
        for candidate in (note_rel.parent / decoded, PurePosixPath(decoded.lstrip("/"))):
            joined = _normalise(candidate)
            if joined is not None and self.exists(joined):
                return joined
        return self.by_name(decoded)


def _normalise(path: PurePosixPath | str) -> PurePosixPath | None:
    """Collapse `.` and `..`; None when it climbs out of the vault."""
    parts: list[str] = []
    for part in PurePosixPath(path).parts:
        if part in (".", ""):
            continue
        if part == "..":
            if not parts:
                return None
            parts.pop()
        else:
            parts.append(part)
    return PurePosixPath(*parts) if parts else None


# --- embeds --------------------------------------------------------------------------------


def _blank_code(body: str) -> str:
    """Blank fenced and inline code so an embed shown as an example is not mistaken for one."""
    out: list[str] = []
    fence: str | None = None
    for line in body.splitlines(keepends=True):
        stripped = line.lstrip()
        marker = stripped[:3]
        if fence is None and marker in ("```", "~~~"):
            fence = marker
            out.append("\n")
        elif fence is not None:
            if marker == fence:
                fence = None
            out.append("\n")
        else:
            out.append(_INLINE_CODE.sub(lambda m: " " * len(m.group(0)), line))
    return "".join(out)


@dataclass(frozen=True)
class Embed:
    ref: str  # the exact text in the note, e.g. `![[shot.png|300]]`: A.4 `ref_in_markdown`
    target: str
    kind: str  # 'wiki' | 'markdown'


def find_embeds(body: str) -> list[Embed]:
    """Attachment embeds in `body`, in document order, one per distinct `ref`."""
    text = _blank_code(body)
    hits: list[tuple[int, Embed]] = []
    for match in _WIKI_EMBED.finditer(text):
        # `![[target#heading|alias or 300]]`: the target is what precedes `|` and `#`.
        target = match.group(1).split("|", 1)[0].split("#", 1)[0].strip()
        if target and PurePosixPath(target).suffix.lower() in ATTACHMENT_EXTENSIONS:
            hits.append((match.start(), Embed(match.group(0), target, "wiki")))
    for match in _MD_IMAGE.finditer(text):
        target = match.group(1)
        if target.startswith("<") and target.endswith(">"):
            target = target[1:-1]
        if _URL_SCHEME.match(target):
            continue  # http(s), data:, file:, ... are not vault files
        if PurePosixPath(unquote(target)).suffix.lower() in ATTACHMENT_EXTENSIONS:
            hits.append((match.start(), Embed(match.group(0), target, "markdown")))
    seen: set[str] = set()
    embeds: list[Embed] = []
    for _, embed in sorted(hits, key=lambda hit: hit[0]):
        if embed.ref not in seen:
            seen.add(embed.ref)
            embeds.append(embed)
    return embeds


# --- per-note facts ------------------------------------------------------------------------


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass
class LocalNote:
    path: str  # vault-relative, POSIX: the manifest's `source_path`
    workspace: str
    arp_id: str | None
    content_hash: str
    size_bytes: int
    attachments: list[dict[str, Any]] = field(default_factory=list)
    unresolved_embeds: list[str] = field(default_factory=list)

    def attachment_hashes(self) -> set[str]:
        return {a["sha256"] for a in self.attachments}

    def as_json(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "workspace": self.workspace,
            "arp_id": self.arp_id,
            "content_hash": self.content_hash,
            "size_bytes": self.size_bytes,
            "attachments": self.attachments,
            "unresolved_embeds": self.unresolved_embeds,
        }


def inspect_note(
    vault_root: Path, index: AttachmentIndex, file: Path, hashes: dict[Path, str]
) -> LocalNote:
    raw = file.read_bytes()
    text = raw.decode("utf-8", errors="replace")
    rel = PurePosixPath(file.relative_to(vault_root).as_posix())
    _, body = split_frontmatter(text)
    note = LocalNote(
        path=str(rel),
        workspace=vault_root.name,
        arp_id=read_arp_id(text),
        content_hash=hashlib.sha256(raw).hexdigest(),
        size_bytes=len(raw),
    )
    for embed in find_embeds(body):
        resolved = (
            index.by_name(embed.target)
            if embed.kind == "wiki"
            else index.resolve_markdown_link(rel, embed.target)
        )
        if resolved is None:
            note.unresolved_embeds.append(embed.ref)
            continue
        target = vault_root / resolved
        if target not in hashes:
            hashes[target] = sha256_file(target)
        note.attachments.append(
            {
                "ref": embed.ref,
                "path": str(resolved),
                "sha256": hashes[target],
                "size_bytes": target.stat().st_size,
            }
        )
    return note


@dataclass
class VaultScope:
    root: Path
    notes: list[LocalNote] = field(default_factory=list)
    scope: list[str] = field(
        default_factory=list
    )  # vault-relative files/folders that were asked for

    def covers(self, rel_path: str) -> bool:
        return any(s == "" or rel_path == s or rel_path.startswith(s + "/") for s in self.scope)


def scan_vault_notes(paths: list[Path]) -> tuple[list[VaultScope], list[dict[str, str]]]:
    """Resolve explicit `paths` (D2) into per-vault note facts. Raises ScanRefusal on bad input."""
    resolved: list[Path] = []
    for raw in paths:
        path = raw.expanduser().resolve()
        if not path.exists():
            raise ScanRefusal(f"no such file or folder: {raw}")
        if is_vault_root(path):
            raise ScanRefusal(
                f"{raw} is an Obsidian vault root (it contains .obsidian/). arp-notes never "
                "syncs a whole vault: pass the files or folders you mean."
            )
        resolved.append(path)

    vaults: dict[Path, VaultScope] = {}
    files_by_vault: dict[Path, set[Path]] = defaultdict(set)
    errors: list[dict[str, str]] = []
    for path in resolved:
        root = find_vault_root(path)
        if root is None:
            raise ScanRefusal(
                f"{path} is not inside an Obsidian vault (no ancestor contains .obsidian/)."
            )
        scope = vaults.setdefault(root, VaultScope(root))
        scope.scope.append(path.relative_to(root).as_posix())
        if path.is_dir():
            files_by_vault[root].update(f for f in _walk(path) if f.suffix.lower() == ".md")
        elif path.suffix.lower() == ".md":
            files_by_vault[root].add(path)
        else:
            errors.append({"path": str(path), "error": "not_markdown"})

    for root, scope in vaults.items():
        index = AttachmentIndex(root)
        hashes: dict[Path, str] = {}
        for file in sorted(files_by_vault[root]):
            try:
                scope.notes.append(inspect_note(root, index, file, hashes))
            except OSError as exc:
                errors.append({"path": str(file), "error": f"unreadable: {exc.strerror or exc}"})
    return list(vaults.values()), errors


# --- classification ------------------------------------------------------------------------


def classify(
    vault: VaultScope, manifest: list[dict[str, Any]]
) -> tuple[dict[str, list[dict[str, Any]]], list[dict[str, str]]]:
    """Sort a vault's scanned notes, and the manifest rows in scope, into the five A.5 buckets.

    - new: no `arp_id` yet, or an `arp_id` the server does not know.
    - changed: known, same path, but the bytes (or the set of attachments) differ, or the server
      has it tombstoned and the file is back (the next sync restores it).
    - renamed: known `arp_id` at a different path. `content_changed` says whether it also changed.
    - unchanged: known, same path, same bytes and attachments.
    - deleted: a live manifest row inside the scanned scope whose `arp_id` no scanned file carries
      and whose path is gone from disk. A note moved out of the scanned scope looks the same.
    """
    buckets: dict[str, list[dict[str, Any]]] = {
        "new": [],
        "changed": [],
        "renamed": [],
        "unchanged": [],
        "deleted": [],
    }
    errors: list[dict[str, str]] = []
    rows = {row["source_doc_id"]: row for row in manifest}

    owners: dict[str, list[LocalNote]] = defaultdict(list)
    for note in vault.notes:
        if note.arp_id:
            owners[note.arp_id].append(note)
    duplicated = {arp_id for arp_id, notes in owners.items() if len(notes) > 1}
    for arp_id in sorted(duplicated):
        for note in owners[arp_id]:
            errors.append(
                {"path": note.path, "error": f"duplicate arp_id {arp_id} (a copied note?)"}
            )

    for note in vault.notes:
        item = note.as_json()
        if note.arp_id in duplicated:
            continue
        row = rows.get(note.arp_id) if note.arp_id else None
        if row is None:
            buckets["new"].append(item)
            continue
        content_changed = (
            row["content_hash"] != note.content_hash
            or set(row.get("attachments") or []) != note.attachment_hashes()
            or bool(row.get("deleted_at"))
        )
        if row["source_path"] != note.path:
            item.update(old_path=row["source_path"], content_changed=content_changed)
            buckets["renamed"].append(item)
        elif content_changed:
            buckets["changed"].append(item)
        else:
            buckets["unchanged"].append(item)

    for row in manifest:
        if row.get("deleted_at") or row["source_doc_id"] in owners:
            continue
        path = row["source_path"]
        if vault.covers(path) and not (vault.root / path).exists():
            buckets["deleted"].append(
                {
                    "path": path,
                    "workspace": vault.root.name,
                    "arp_id": row["source_doc_id"],
                    "last_synced_at": row.get("last_synced_at"),
                }
            )
    return buckets, errors


def scan(
    client: NotesClient, vaults: list[VaultScope], errors: list[dict[str, str]]
) -> tuple[dict[str, list[dict[str, Any]]], list[dict[str, str]]]:
    """Classify already-inspected `vaults` against the host. `errors` is extended, not copied."""
    result: dict[str, list[dict[str, Any]]] = {
        "new": [],
        "changed": [],
        "renamed": [],
        "unchanged": [],
        "deleted": [],
    }
    errors = list(errors)
    for vault in vaults:
        buckets, vault_errors = classify(vault, client.manifest(SOURCE_SYSTEM, vault.root.name))
        for name, items in buckets.items():
            result[name].extend(items)
        errors.extend(vault_errors)
    return result, errors


# --- command -------------------------------------------------------------------------------


def _print_human(result: dict[str, list[dict[str, Any]]], errors: list[dict[str, str]]) -> None:
    for name, items in result.items():
        print(f"{name} ({len(items)})")
        for item in items:
            line = f"  {item['workspace']}: {item['path']}"
            if name == "renamed":
                line += f"  (was {item['old_path']})"
            if item.get("unresolved_embeds"):
                line += f"  [{len(item['unresolved_embeds'])} unresolved embed(s)]"
            print(line)
    for error in errors:
        print(f"error: {error['path']}: {error['error']}", file=sys.stderr)


def _cmd_scan(args: argparse.Namespace) -> int:
    def body() -> int:
        try:  # judge the paths first: a refusal needs no app, token or network
            vaults, local_errors = scan_vault_notes([Path(p) for p in args.paths])
        except ScanRefusal as exc:
            raise ConfigError(str(exc)) from exc
        with open_client(args.app) as client:
            result, errors = scan(client, vaults, local_errors)
        if args.json:
            print(json.dumps({**result, "errors": errors}, indent=2, ensure_ascii=False))
        else:
            _print_human(result, errors)
        return 1 if errors else 0

    return run_command("scan", body)


def register(subparsers: Subparsers) -> None:
    parser = subparsers.add_parser(
        "scan",
        help="Diff explicit files/folders against the server manifest. No writes.",
        description=(
            "Compare the given files and folders with what the host already has and print "
            "{new, changed, renamed, unchanged, deleted}. Writes nothing, locally or remotely. "
            "A vault root is refused: name the files or folders to consider (D2)."
        ),
    )
    parser.add_argument("paths", nargs="+", help="Markdown files or folders inside a vault")
    add_app_argument(parser)
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.set_defaults(func=_cmd_scan)
