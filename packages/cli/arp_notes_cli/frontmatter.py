"""Frontmatter: the one-line `arp_id` insert (D1) and the Obsidian adapter rules (A.5).

Owner: CLI-b ga-mxal.36.

The CLI writes to a vault exactly once per note, by inserting a single `arp_id: <uuid4>` line after
the opening `---` (creating a frontmatter block when there is none). It never parses and
re-serialises the user's YAML, so keys with spaces, Templater expressions, dataview inline fields,
CRLF line endings and a BOM all survive byte for byte. `parse_frontmatter` below is read only and
lenient: it feeds the wire's `frontmatter` field and the title/date/person/kind rules, nothing else.
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import PurePosixPath
from typing import Any

from arp_notes_cli.scan import read_arp_id, split_frontmatter

BOM = b"\xef\xbb\xbf"

_LINE_END = re.compile(r"\r\n|\n|\r")
_ARP_ID_KEY = re.compile(r"^arp_id[ \t]*:", re.MULTILINE)
_TOP_KEY = re.compile(r"^([^\s#\-][^:]*?)[ \t]*:(?:[ \t]+(.*?))?[ \t]*$")
_ISO_DATE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})(?![\d])")
_WIKILINK = re.compile(r"\[\[([^\]\n|#]+)")
_INLINE_PERSON_FIELD = re.compile(
    r"^[ \t]*(?:[-*+][ \t]+)?\**[ \t]*(?:attendees|presenter|author)[ \t]*\**[ \t]*::[ \t]*(.*)$",
    re.IGNORECASE,
)
_FRONTMATTER_PERSON_KEYS = ("attendees", "presenter", "author")
_DATE_KEYS = ("meeting-date", "date", "created")

# D8. Free to extend on the host; these are the ones the heuristics can name.
KINDS = ("masterclass", "workshop", "lecture", "reading", "video", "reflection", "meeting")
_TAG_KINDS = {"meetingnote": "meeting", "meetingnotes": "meeting"}


class FrontmatterError(Exception):
    """A note whose frontmatter the one-line insert cannot handle safely."""


# --- arp_id insert (D1) --------------------------------------------------------------------


def ensure_arp_id(raw: bytes, new_id: str) -> tuple[bytes, str, bool]:
    """Return (bytes to store, the note's arp_id, whether anything was inserted).

    A note that already carries an `arp_id` comes back untouched. Otherwise exactly one line is
    added, using the file's own line ending, directly after the opening `---`; a note with no
    frontmatter block gets a three-line block in front of everything (after a BOM, if any).
    Every original byte is still there, in order.
    """
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise FrontmatterError("not valid UTF-8, so it cannot be synced verbatim") from exc

    existing = read_arp_id(text)
    if existing:
        return raw, existing, False

    bom = BOM if raw.startswith(BOM) else b""
    body = text[1:] if bom else text  # drop the BOM character; `raw` still has the bytes
    first = _LINE_END.search(body)
    newline = first.group(0) if first else "\n"

    block, _ = split_frontmatter(text)
    if block is not None:
        if _ARP_ID_KEY.search(block):
            raise FrontmatterError(
                "frontmatter has an `arp_id` key with no value: fill it in or delete the line"
            )
        # split_frontmatter found a block, so the first line is exactly `---` plus its terminator.
        assert first is not None
        newline = first.group(0)
        cut = first.end()
        line = f"arp_id: {new_id}{newline}"
        inserted = body[:cut] + line + body[cut:]
    else:
        inserted = f"---{newline}arp_id: {new_id}{newline}---{newline}" + body
    return bom + inserted.encode("utf-8"), new_id, True


# --- lenient read of the block -------------------------------------------------------------


def _unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def _split_flow(inner: str) -> list[str]:
    """Split `a, "b, c", d` on top-level commas."""
    items: list[str] = []
    current: list[str] = []
    quote: str | None = None
    for char in inner:
        if quote:
            current.append(char)
            if char == quote:
                quote = None
        elif char in "\"'":
            quote = char
            current.append(char)
        elif char == ",":
            items.append("".join(current))
            current = []
        else:
            current.append(char)
    items.append("".join(current))
    return [_unquote(item) for item in items if item.strip()]


def _scalar(value: str) -> str | list[str]:
    value = value.strip()
    # `[[Roy Howat]]` is a wikilink, not a flow sequence.
    if value.startswith("[") and value.endswith("]") and not value.startswith("[["):
        return _split_flow(value[1:-1])
    return _unquote(value)


def parse_frontmatter(block: str | None) -> dict[str, Any]:
    """Top-level `key: value` pairs as strings, string lists, or raw text; never raises.

    Block sequences (`- item`) become lists; indented continuations of any other key are joined
    into one string. Values are not typed (`25` stays "25", a date stays a string, a Templater
    expression stays its source text), which is what "unknown constructs kept as strings" means.
    """
    result: dict[str, Any] = {}
    if not block:
        return result
    key: str | None = None
    continuation: list[str] = []

    def flush() -> None:
        if key is None or not continuation:
            return
        items = [c.strip() for c in continuation]
        if all(i.startswith("- ") or i == "-" for i in items):
            result[key] = [_unquote(i[1:]) for i in items if i[1:].strip()]
        else:
            joined = "\n".join(i for i in items if i)
            existing = result.get(key)
            result[key] = (
                f"{existing}\n{joined}" if isinstance(existing, str) and existing else joined
            )

    for line in block.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        match = _TOP_KEY.match(line) if line[0] not in " \t" else None
        if match:
            flush()
            continuation = []
            name = str(match.group(1))
            key = name
            value = match.group(2) or ""
            if value in ("|", ">", "|-", ">-", "|+", ">+") or not value:
                result[name] = ""
            else:
                result[name] = _scalar(value)
        elif key is not None and (line[0] in " \t" or line.startswith("-")):
            continuation.append(line)
    flush()
    return result


# --- Obsidian adapter rules (A.5) ----------------------------------------------------------


def _strings(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(v) for v in value]
    return [str(value)] if value not in (None, "") else []


def _iso_date(value: str) -> str | None:
    match = _ISO_DATE.match(value.strip())
    if not match:
        return None
    try:
        return date(int(match[1]), int(match[2]), int(match[3])).isoformat()
    except ValueError:
        return None


def derive_title(frontmatter: dict[str, Any], path: str) -> str:
    title = frontmatter.get("title")
    if isinstance(title, str) and title.strip():
        return title.strip()
    return PurePosixPath(path).stem


def derive_note_date(frontmatter: dict[str, Any], path: str) -> str | None:
    """`meeting-date`, `date` or `created` when ISO, else a leading YYYY-MM-DD in the filename."""
    for key in _DATE_KEYS:
        for value in _strings(frontmatter.get(key)):
            found = _iso_date(value)
            if found:
                return found
    return _iso_date(PurePosixPath(path).name)


def _inline_person_values(body: str) -> list[str]:
    values: list[str] = []
    fence: str | None = None
    for line in body.splitlines():
        marker = line.lstrip()[:3]
        if fence is None and marker in ("```", "~~~"):
            fence = marker
        elif fence is not None:
            if marker == fence:
                fence = None
        else:
            match = _INLINE_PERSON_FIELD.match(line)
            if match:
                values.append(match.group(1))
    return values


def derive_person(frontmatter: dict[str, Any], body: str) -> str | None:
    """First `[[…]]` in frontmatter `presenter`/`author`/`attendees` or a body `Attendees::`."""
    candidates: list[str] = []
    for key in _FRONTMATTER_PERSON_KEYS:
        candidates.extend(_strings(frontmatter.get(key)))
    candidates.extend(_inline_person_values(body))
    for candidate in candidates:
        match = _WIKILINK.search(candidate)
        if match and match.group(1).strip():
            return match.group(1).strip()
    return None


def _kind_in(text: str) -> str | None:
    lowered = text.lower()
    return next((kind for kind in KINDS if kind in lowered), None)


def guess_kind(frontmatter: dict[str, Any], path: str) -> str | None:
    """D8 heuristics. A kind named in the title or filename wins over a generic tag.

    `tags: MeetingNote` gives `meeting`; "masterclass" in the title gives `masterclass`. None when
    nothing matches, so the host applies its own default (and a kind the user later edits in the
    host is not overwritten by a guess on every sync).
    """
    named = _kind_in(derive_title(frontmatter, path)) or _kind_in(PurePosixPath(path).stem)
    if named:
        return named
    tags: list[str] = []
    for key in ("tags", "tag"):
        for value in _strings(frontmatter.get(key)):
            tags.extend(re.split(r"[\s,]+", value))
    for tag in tags:
        normal = re.sub(r"[^a-z0-9]", "", tag.lower().split("/")[0])
        if normal in _TAG_KINDS:
            return _TAG_KINDS[normal]
        if normal in KINDS:
            return normal
    return None
