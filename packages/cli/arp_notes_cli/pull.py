"""`arp-notes pull`: export host notes to Markdown plus attachments (ADR §3.7, A.5).

Owner: CLI-c ga-mxal.37.

Per note: (1) `GET /notes/{id}/export` for the Markdown and the `X-Arp-Attachments` manifest (the
note's own `attachments` when the header is absent), (2) decide where the note goes and what its
attachments are called, (3) download each attachment from its signed URL, hash-checked, beside the
note, (4) rewrite the embeds to point at those files, (5) write the note. Everything that can refuse
is decided before anything is written, so a refused note leaves the folder as it was.

Identity is the `arp_id` in the exported frontmatter. A note already in the folder (by `arp_id`,
wherever it sits) is updated in place, so a note renamed in the host never leaves two files with
one `arp_id`. A different note, or a file of yours, that holds the wanted name is never touched:
the new file takes `Name (2).md`. Only `--force` replaces a pulled note whose content differs.
`exported_at` changes on every export, so it is ignored when deciding whether a file differs.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import uuid
from collections import defaultdict
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import unquote, urljoin

import httpx

from arp_notes_cli.client import ClientError, NotesClient, _error_detail, run_command
from arp_notes_cli.config import ConfigError, add_app_argument, get_app, load_token
from arp_notes_cli.registry import Subparsers
from arp_notes_cli.scan import COMPANION_SUFFIX, read_arp_id, sha256_file, split_frontmatter

LIST_PAGE_LIMIT = 100  # A.2: GET /notes limit 1..100
DOWNLOAD_TIMEOUT_S = 120.0
DOWNLOAD_CHUNK = 1 << 20
FRONTMATTER_HEAD = 1 << 16  # how much of an existing file is read to find its arp_id
MAX_STEM = 100  # characters kept from a title or attachment name

STYLES = ("frontmatter", "companion")

# Obsidian refuses these in file names; the rest are unsafe on some filesystem.
_UNSAFE_NAME = re.compile(r'[\\/:*?"<>|#^\[\]\x00-\x1f\x7f]')
_INLINE_CODE = re.compile(r"`[^`\n]*`")
_MD_DESTINATION = re.compile(r"\]\(\s*(<[^>\n]*>|[^)\s]+)")
_WIKI_TARGET = re.compile(r"([^|#]*)(.*)", re.DOTALL)
_EXPORTED_AT = re.compile(r"^exported_at[ \t]*:")
_NOTE_ID = re.compile(r"^\d+$")


# --- http: the two calls that are not JSON --------------------------------------------------


class PullClient(NotesClient):
    """NotesClient plus the export (text with headers) and the signed-URL downloads."""

    def export(self, note_id: int, *, with_enrichment: bool, style: str) -> httpx.Response:
        if not self._token:
            raise ClientError(
                f"no API token for app {self.app.name!r}: run `arp-notes login --app "
                f"{self.app.name} --url {self.app.url}` or set ARP_NOTES_TOKEN"
            )
        url = f"{self.app.api_base}/notes/{note_id}/export"
        params = {"with_enrichment": "true", "enrichment_style": style} if with_enrichment else {}
        try:
            response = self._http.get(
                url,
                params=params,
                headers={"Authorization": f"Bearer {self._token}", "Accept": "text/markdown"},
            )
        except httpx.HTTPError as exc:
            raise ClientError(f"cannot reach {url}: {exc}") from exc
        if response.status_code >= 400:
            detail, body = _error_detail(response)
            raise ClientError(
                f"GET {url} -> HTTP {response.status_code}: {detail}",
                status=response.status_code,
                body=body,
            )
        return response

    def download(self, content_url: str, dest: Path, *, sha256: str) -> None:
        """Stream a signed `content_url` to `dest`, only keeping it when the bytes hash to `sha256`.

        The URL is the credential (A.4 serving), so no Bearer is sent: the token never leaves for
        a host the signed URL might name.
        """
        url = urljoin(self.app.api_base + "/", content_url)
        tmp = _temp_beside(dest)
        digest = hashlib.sha256()
        try:
            with httpx.stream("GET", url, timeout=DOWNLOAD_TIMEOUT_S) as response:
                if response.status_code != 200:
                    response.read()
                    detail, _ = _error_detail(response)
                    raise ClientError(
                        f"download {dest.name} -> HTTP {response.status_code}: {detail}",
                        status=response.status_code,
                    )
                with tmp.open("xb") as handle:
                    for chunk in response.iter_bytes(DOWNLOAD_CHUNK):
                        digest.update(chunk)
                        handle.write(chunk)
            if digest.hexdigest() != sha256:
                raise ClientError(
                    f"download of {dest.name} does not match its sha256 {sha256}: not kept"
                )
            os.replace(tmp, dest)
        except httpx.HTTPError as exc:
            raise ClientError(f"cannot download {dest.name}: {exc}") from exc
        finally:
            tmp.unlink(missing_ok=True)


# --- choosing notes ----------------------------------------------------------------------


@dataclass(frozen=True)
class Target:
    note_id: int
    title: str | None = None  # known already (from a listing), saves a GET /notes/{id}


def iter_notes(client: NotesClient, **params: Any) -> Iterator[dict[str, Any]]:
    """Every NoteSummary of `GET /notes` for `params`, following `next_cursor`."""
    cursor: str | None = None
    seen: set[str] = set()
    while True:
        page = client.request(
            "GET", "/notes", params={"limit": LIST_PAGE_LIMIT, "before": cursor, **params}
        )
        if not isinstance(page, dict) or not isinstance(page.get("items"), list):
            raise ClientError("GET /notes has no `items` list")
        yield from page["items"]
        cursor = page.get("next_cursor")
        if not cursor:
            return
        if str(cursor) in seen:
            raise ClientError("note paging does not advance (next_cursor repeats)")
        seen.add(str(cursor))


def resolve_arp_ids(client: NotesClient, arp_ids: list[str]) -> tuple[dict[str, int], list[str]]:
    """Find the note id behind each `arp_id`: manifest row -> path -> listed note -> confirmed.

    A.2 has no lookup by `arp_id`, so this goes through what it does have. A path can be shared by
    an old and a new note, so the match is confirmed against `source_doc_id` on `GET /notes/{id}`.
    """
    try:
        sources = client.sync_sources()
    except ClientError as exc:
        raise ClientError(f"cannot look up arp_ids ({exc}); pass numeric note ids instead") from exc
    found: dict[str, int] = {}
    for source in sources:
        wanted = [i for i in arp_ids if i not in found]
        if not wanted:
            break
        system, workspace = source["source_system"], source["source_workspace"]
        paths: dict[str, set[str]] = defaultdict(set)
        for row in client.manifest(system, workspace):
            if row["source_doc_id"] in wanted:
                paths[row["source_path"]].add(row["source_doc_id"])
        if not paths:
            continue
        for summary in iter_notes(client, source_system=system, include_deleted=True):
            wanted_here = paths.get(summary.get("source_path", ""))
            if summary.get("source_workspace") != workspace or not wanted_here:
                continue
            note = client.request("GET", f"/notes/{summary['id']}")
            doc_id = note.get("source_doc_id") if isinstance(note, dict) else None
            if doc_id in wanted_here and doc_id not in found:
                found[doc_id] = int(summary["id"])
    return found, [i for i in arp_ids if i not in found]


def choose_targets(
    client: NotesClient, names: list[str], all_app_notes: bool
) -> tuple[list[Target], list[dict[str, str]]]:
    targets: dict[int, Target] = {}
    errors: list[dict[str, str]] = []
    arp_ids: list[str] = []
    for name in dict.fromkeys(names):
        if _NOTE_ID.match(name):
            targets.setdefault(int(name), Target(int(name)))
        else:
            arp_ids.append(name)
    if arp_ids:
        found, unknown = resolve_arp_ids(client, arp_ids)
        for note_id in found.values():
            targets.setdefault(note_id, Target(note_id))
        errors.extend(
            {
                "id": arp_id,
                "error": "unknown arp_id (an app-authored note has no source id: pass its "
                "numeric note id, or --all-app-notes)",
            }
            for arp_id in unknown
        )
    if all_app_notes:
        for summary in iter_notes(client, origin="app"):
            targets.setdefault(int(summary["id"]), Target(int(summary["id"]), summary.get("title")))
    return list(targets.values()), errors


# --- names ------------------------------------------------------------------------------


def safe_stem(name: str, fallback: str) -> str:
    cleaned = re.sub(r"\s+", " ", _UNSAFE_NAME.sub("-", name)).strip(" .")
    return cleaned[:MAX_STEM].rstrip(" .") or fallback


def safe_attachment_name(filename: str) -> tuple[str, str]:
    """(stem, suffix) for a host-supplied attachment filename, with any directory dropped."""
    base = PurePosixPath(filename.replace("\\", "/")).name
    suffix = PurePosixPath(base).suffix
    stem = safe_stem(base[: len(base) - len(suffix)], "attachment")
    return stem, _UNSAFE_NAME.sub("-", suffix)[:16]


def numbered(stem: str, suffix: str) -> Iterator[str]:
    yield f"{stem}{suffix}"
    count = 2
    while True:
        yield f"{stem} ({count}){suffix}"
        count += 1


def companion_for(note: Path) -> Path:
    """`Name.md` -> `Name.arp.md` (string surgery: `with_suffix` mangles `Dr. Smith.md`)."""
    return note.with_name(note.name[: -len(".md")] + COMPANION_SUFFIX)


def _temp_beside(path: Path) -> Path:
    return path.with_name(f".{path.name}.arp-{uuid.uuid4().hex[:8]}.tmp")


def write_atomic(path: Path, data: bytes) -> None:
    """Write beside, then rename over: an interrupted run leaves the old file whole."""
    tmp = _temp_beside(path)
    try:
        with tmp.open("xb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        if path.exists():
            shutil.copymode(path, tmp)
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


# --- embeds -----------------------------------------------------------------------------


def _blank(text: str) -> str:
    return "".join(c if c in "\r\n" else "\x00" for c in text)


def mask_code(text: str) -> str:
    """`text` with fenced and inline code blanked, same length, so offsets still line up."""
    out: list[str] = []
    fence: str | None = None
    for line in text.splitlines(keepends=True):
        marker = line.lstrip()[:3]
        if fence is None and marker in ("```", "~~~"):
            fence = marker
            out.append(_blank(line))
        elif fence is not None:
            if marker == fence:
                fence = None
            out.append(_blank(line))
        else:
            out.append(_INLINE_CODE.sub(lambda m: _blank(m.group(0)), line))
    return "".join(out)


def _escape_destination(filename: str) -> str:
    return re.sub(r"[ ()%]", lambda m: f"%{ord(m.group(0)):02X}", filename)


def rewrite_ref(ref: str, filename: str) -> str | None:
    """`ref` (an embed exactly as stored) pointing at `filename` beside the note.

    The syntax, alias and size are kept: `![[a/b.png|300]]` becomes `![[b.png|300]]`, and
    `![shot](attachment://7)` becomes `![shot](b.png)`. None when `ref` is neither form.
    """
    if ref.endswith("]]") and "[[" in ref:
        opener = ref.index("[[") + 2
        match = _WIKI_TARGET.fullmatch(ref[opener:-2])
        if match is None:
            return None
        if match.group(1).strip() == filename:
            return ref
        return f"{ref[:opener]}{filename}{match.group(2)}]]"
    match = _MD_DESTINATION.search(ref)
    if match is None:
        return None
    destination = match.group(1)
    raw = destination[1:-1] if destination.startswith("<") else destination
    if unquote(raw) in (filename, f"./{filename}"):
        return ref
    return ref[: match.start(1)] + _escape_destination(filename) + ref[match.end(1) :]


def replace_refs(text: str, replacements: dict[str, str]) -> str:
    """Replace each embed outside code. Offsets come from the masked copy, edits go to the text."""
    masked = mask_code(text)
    spans: list[tuple[int, int, str]] = []
    for old, new in replacements.items():
        if old == new:
            continue
        start = masked.find(old)
        while start != -1:
            spans.append((start, start + len(old), new))
            start = masked.find(old, start + len(old))
    out: list[str] = []
    cursor = 0
    for begin, end, new in sorted(spans):
        if begin < cursor:  # overlaps an earlier edit: leave it alone
            continue
        out.append(text[cursor:begin])
        out.append(new)
        cursor = end
    out.append(text[cursor:])
    return "".join(out)


# --- reading what the host sent -----------------------------------------------------------


def decode_markdown(response: httpx.Response) -> str:
    try:
        return response.content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ClientError("the export is not valid UTF-8") from exc


def parse_attachments_header(value: str | None) -> list[dict[str, Any]] | None:
    """The `X-Arp-Attachments` JSON list, or None when absent or unusable (caller falls back)."""
    if not value or not value.strip():
        return None
    try:
        parsed = json.loads(value)
    except ValueError:
        return None
    return parsed if isinstance(parsed, list) else None


_ATTACHMENT_FIELDS = ("sha256", "filename", "ref_in_markdown", "content_url")


def checked_attachments(raw: list[Any]) -> list[dict[str, Any]]:
    for item in raw:
        if not isinstance(item, dict) or any(
            not isinstance(item.get(key), str) for key in _ATTACHMENT_FIELDS
        ):
            raise ClientError(f"an attachment in the export lacks one of {_ATTACHMENT_FIELDS}")
    return raw


def comparable(text: str) -> str:
    """`text` without its `exported_at` line, the one thing that differs between two exports."""
    block, _ = split_frontmatter(text)
    if not block:
        return text
    kept = "".join(line for line in block.splitlines(keepends=True) if not _EXPORTED_AT.match(line))
    return text.replace(block, kept, 1)


def same_content(existing: Path, new: bytes) -> bool:
    try:
        current = existing.read_bytes()
    except OSError:
        return False
    if current == new:
        return True
    try:
        return comparable(current.decode("utf-8")) == comparable(new.decode("utf-8"))
    except UnicodeDecodeError:
        return False


def index_folder(folder: Path) -> tuple[dict[str, Path], set[str]]:
    """`arp_id` -> the note file already holding it, and the ids that more than one file holds."""
    found: dict[str, Path] = {}
    shared: set[str] = set()
    for dirpath, dirnames, filenames in os.walk(folder):
        dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
        for name in sorted(filenames):
            lowered = name.lower()
            if not lowered.endswith(".md") or lowered.endswith(COMPANION_SUFFIX):
                continue
            path = Path(dirpath) / name
            try:
                with path.open("rb") as handle:
                    head = handle.read(FRONTMATTER_HEAD).decode("utf-8", errors="replace")
            except OSError:
                continue
            arp_id = read_arp_id(head)
            if not arp_id:
                continue
            if arp_id in found:
                shared.add(arp_id)
            else:
                found[arp_id] = path
    return found, shared


# --- pulling ----------------------------------------------------------------------------


class Refused(Exception):
    """A file in the folder that pull will not replace without --force. Nothing was written."""


@dataclass
class Options:
    with_enrichment: bool = False
    style: str = "frontmatter"
    force: bool = False


@dataclass
class Report:
    pulled: list[dict[str, Any]] = field(default_factory=list)
    errors: list[dict[str, str]] = field(default_factory=list)
    warnings: list[dict[str, str]] = field(default_factory=list)

    def as_json(self) -> dict[str, Any]:
        out: dict[str, Any] = {"pulled": self.pulled, "errors": self.errors}
        if self.warnings:
            out["warnings"] = self.warnings
        return out


@dataclass
class PlannedAttachment:
    meta: dict[str, Any]
    path: Path
    present: bool  # the file is already there with the right bytes


class Puller:
    def __init__(self, client: PullClient, folder: Path, options: Options) -> None:
        self.client = client
        self.folder = folder
        self.options = options
        self.report = Report()
        self.index, self.shared = index_folder(folder)

    # -- naming

    def _note_path(self, arp_id: str | None, title: str) -> Path:
        if arp_id and arp_id in self.shared:
            raise Refused(
                f"more than one file in the folder carries arp_id {arp_id}; fix that first"
            )
        if arp_id and arp_id in self.index:
            return self.index[arp_id]
        stem = safe_stem(title, "Untitled")
        for name in numbered(stem, ".md"):
            candidate = self.folder / name
            if not candidate.exists() and not companion_for(candidate).exists():
                return candidate
        raise AssertionError("unreachable")  # numbered() never ends

    def _plan_attachments(
        self, directory: Path, attachments: list[dict[str, Any]]
    ) -> list[PlannedAttachment]:
        """Name each attachment: its own filename if free or already holding these bytes."""
        planned: list[PlannedAttachment] = []
        claimed: dict[str, str] = {}  # casefolded name -> sha256, within this note
        for meta in attachments:
            stem, suffix = safe_attachment_name(meta["filename"])
            for name in numbered(stem, suffix):
                key = name.casefold()
                path = directory / name
                if key in claimed:
                    if claimed[key] == meta["sha256"]:  # the same image embedded twice
                        planned.append(PlannedAttachment(meta, path, present=True))
                        break
                    continue
                if not path.exists():
                    claimed[key] = meta["sha256"]
                    planned.append(PlannedAttachment(meta, path, present=False))
                    break
                if path.is_file() and sha256_file(path) == meta["sha256"]:
                    claimed[key] = meta["sha256"]
                    planned.append(PlannedAttachment(meta, path, present=True))
                    break
        return planned

    # -- deciding

    def _outcome(self, path: Path, data: bytes) -> str:
        if not path.exists():
            return "created"
        if same_content(path, data):
            return "unchanged"
        if self.options.force:
            return "updated"
        raise Refused(
            f"{path.relative_to(self.folder).as_posix()} exists and differs (edited here, or "
            "changed in the app); re-run with --force to replace it"
        )

    # -- one note

    def pull(self, target: Target) -> None:
        opts = self.options
        note_id = target.note_id
        companion = opts.with_enrichment and opts.style == "companion"
        response = self.client.export(
            note_id, with_enrichment=opts.with_enrichment and not companion, style=opts.style
        )
        text = decode_markdown(response)
        companion_text = (
            decode_markdown(self.client.export(note_id, with_enrichment=True, style="companion"))
            if companion
            else None
        )

        cached: dict[str, Any] = {}

        def note_info() -> dict[str, Any]:
            if "note" not in cached:
                note = self.client.request("GET", f"/notes/{note_id}")
                if not isinstance(note, dict):
                    raise ClientError(f"GET /notes/{note_id} did not return a note")
                cached["note"] = note
            return cached["note"]

        raw = parse_attachments_header(response.headers.get("X-Arp-Attachments"))
        attachments = checked_attachments(
            raw if raw is not None else note_info().get("attachments") or []
        )
        title = target.title or note_info().get("title") or f"note-{note_id}"
        arp_id = read_arp_id(text)
        if arp_id is None:
            self.report.warnings.append(
                {
                    "id": str(note_id),
                    "warning": "the export has no arp_id, so a later sync cannot recognise this "
                    "note as the same one",
                }
            )

        path = self._note_path(arp_id, str(title))
        plan = self._plan_attachments(path.parent, attachments)
        replacements: dict[str, str] = {}
        for item in plan:
            ref = item.meta["ref_in_markdown"]
            new_ref = rewrite_ref(ref, item.path.name)
            if new_ref is None:
                self.report.warnings.append(
                    {
                        "id": str(note_id),
                        "warning": f"cannot point {ref!r} at {item.path.name}; left as stored",
                    }
                )
            else:
                replacements[ref] = new_ref
        data = replace_refs(text, replacements).encode("utf-8")
        outcome = self._outcome(path, data)

        companion_path = companion_for(path)
        companion_data = companion_text.encode("utf-8") if companion_text is not None else None
        companion_outcome = (
            self._outcome(companion_path, companion_data) if companion_data is not None else None
        )

        # Nothing above wrote anything; from here on the note is committed to.
        files: list[dict[str, Any]] = []
        written: set[Path] = set()
        for item in plan:
            if item.path in written:
                continue
            written.add(item.path)
            if not item.present:
                self.client.download(
                    item.meta["content_url"], item.path, sha256=item.meta["sha256"]
                )
            files.append(
                {
                    "path": item.path.relative_to(self.folder).as_posix(),
                    "sha256": item.meta["sha256"],
                    "outcome": "unchanged" if item.present else "created",
                }
            )
        if outcome != "unchanged":
            path.parent.mkdir(parents=True, exist_ok=True)
            write_atomic(path, data)
        if arp_id:
            self.index[arp_id] = path
        result: dict[str, Any] = {
            "note_id": note_id,
            "arp_id": arp_id,
            "path": path.relative_to(self.folder).as_posix(),
            "outcome": outcome,
            "attachments": files,
        }
        if companion_data is not None and companion_outcome is not None:
            if companion_outcome != "unchanged":
                write_atomic(companion_path, companion_data)
            result["companion"] = {
                "path": companion_path.relative_to(self.folder).as_posix(),
                "outcome": companion_outcome,
            }
        self.report.pulled.append(result)

    # -- whole run

    def run(self, targets: list[Target]) -> Report:
        aborted: str | None = None
        for target in targets:
            label = str(target.note_id)
            if aborted:
                self.report.errors.append({"id": label, "error": f"not attempted: {aborted}"})
                continue
            try:
                self.pull(target)
            except Refused as exc:
                self.report.errors.append({"id": label, "error": str(exc)})
            except ClientError as exc:
                self.report.errors.append({"id": label, "error": str(exc)})
                if exc.status is None or exc.status in (401, 403):
                    aborted = str(exc)
            except OSError as exc:
                self.report.errors.append(
                    {"id": label, "error": f"file error: {exc.strerror or exc}"}
                )
        return self.report


# --- command ----------------------------------------------------------------------------


def _print_human(report: Report) -> None:
    for item in report.pulled:
        count = len(item["attachments"])
        extra = f", {count} attachment{'s' if count != 1 else ''}" if count else ""
        print(f"{item['outcome']}  {item['path']}  (note {item['note_id']}{extra})")
        if "companion" in item:
            print(f"{item['companion']['outcome']}  {item['companion']['path']}")
    for warning in report.warnings:
        print(f"warning: note {warning['id']}: {warning['warning']}", file=sys.stderr)
    for error in report.errors:
        print(f"error: {error['id']}: {error['error']}", file=sys.stderr)


def _cmd_pull(args: argparse.Namespace) -> int:
    def body() -> int:
        if not args.ids and not args.all_app_notes:
            raise ConfigError(
                "name the notes to pull (arp_ids or note ids), or pass --all-app-notes"
            )
        if args.enrichment_style and not args.with_enrichment:
            raise ConfigError("--enrichment-style needs --with-enrichment")
        folder = Path(args.to).expanduser()
        if folder.exists() and not folder.is_dir():
            raise ConfigError(f"--to {args.to} is not a folder")
        options = Options(
            with_enrichment=args.with_enrichment,
            style=args.enrichment_style or "frontmatter",
            force=args.force,
        )
        client = PullClient(get_app(args.app), load_token(args.app))
        with client:
            if client.capabilities().get("export") is False:
                raise ClientError("this host has export turned off, so there is nothing to pull")
            targets, unresolved = choose_targets(client, args.ids, args.all_app_notes)
            folder.mkdir(parents=True, exist_ok=True)
            report = Puller(client, folder.resolve(), options).run(targets)
        report.errors[:0] = unresolved
        if args.json:
            print(json.dumps(report.as_json(), indent=2, ensure_ascii=False))
        else:
            _print_human(report)
        return 1 if report.errors else 0

    return run_command("pull", body)


def register(subparsers: Subparsers) -> None:
    parser = subparsers.add_parser(
        "pull",
        help="Export app notes to Markdown plus attachments.",
        description=(
            "Write notes from the host to a folder as Markdown, with their attachments beside "
            "them, embeds pointing at those files and `arp_id` in the frontmatter, so a later "
            "`sync` of the folder round-trips. Existing files are never overwritten unless "
            "--force: a different note's name is taken by numbering (`Name (2).md`). Prints "
            "{pulled, errors}; exits non-zero if any note failed."
        ),
    )
    parser.add_argument(
        "ids",
        nargs="*",
        metavar="id",
        help="arp_id of a synced note, or the numeric note id (app-authored notes have no "
        "source arp_id: use their note id)",
    )
    add_app_argument(parser)
    parser.add_argument(
        "--all-app-notes", action="store_true", help="pull every note written in the app"
    )
    parser.add_argument("--to", required=True, metavar="FOLDER", help="folder to write into")
    parser.add_argument(
        "--with-enrichment",
        action="store_true",
        help="also export links, takeaways and action items (opt-in)",
    )
    parser.add_argument(
        "--enrichment-style",
        choices=STYLES,
        help="enrichment as frontmatter properties (default) or a companion <name>.arp.md file",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="replace a pulled note file whose content differs from the host's",
    )
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.set_defaults(func=_cmd_pull)
