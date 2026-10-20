"""Conformance: export, and the round trip that makes it portable (ADR §3.7, R§7).

Owner: C7b ga-mxal.38. "A component for AI-forward applications, not a walled garden": a note a
user put in the app must come out as Markdown plus its files, and syncing what came out must put
the same bytes back. The kit plays the `arp-notes pull` and `arp-notes sync` roles itself, over
HTTP, so any stack can prove it:

- **pull**: `GET /notes/{id}/export` for the Markdown and the `X-Arp-Attachments` manifest, then
  each attachment from its signed URL, hash-checked against the manifest;
- **sync**: the pulled text goes back through `POST /notes/sync/upsert` with the same identity
  (the `arp_id` in its frontmatter, D1) and the pulled files' own sha256s.

The wire protocol has no call that attaches a file to an app-authored note (`POST /notes` takes no
attachments; the editor's upload is host UI), so the attachment leg of the round trip starts from
an imported note, whose export is verbatim. The app-authored leg proves the frontmatter, the
stable `arp_id` and the fixpoint: export, sync and export again gives the same text.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .harness import REJECTED, UNKNOWN_ID, CheckFailed, CheckSkipped, Harness, sha256_hex
from .suite_attach import Blob, attachments_on, new_blob, upload, upsert_with
from .suite_core import link_target, need, same

Check = Callable[[Harness], None]
CHECKS: list[tuple[str, Check]] = []

_FENCE = re.compile(r"\A---[ \t]*\r?\n(.*?)^(?:---|\.\.\.)[ \t]*\r?$", re.DOTALL | re.MULTILINE)


def check(name: str) -> Callable[[Check], Check]:
    def register(fn: Check) -> Check:
        CHECKS.append((name, fn))
        return fn

    return register


@dataclass
class Pulled:
    """What `arp-notes pull` ends up with for one note."""

    text: str
    part: str
    attachments: list[dict[str, Any]]
    files: dict[str, bytes]  # the manifest's `ref_in_markdown` -> the downloaded bytes


def frontmatter(text: str) -> dict[str, str]:
    """Top-level `key: value` pairs of a leading frontmatter block (enough for the export's own)."""
    match = _FENCE.match(text)
    if match is None:
        return {}
    pairs: dict[str, str] = {}
    for line in match.group(1).splitlines():
        found = re.match(r"([A-Za-z_][\w-]*)\s*:\s*(.*)$", line)
        if found:
            pairs[found.group(1)] = found.group(2).strip().strip("'\"")
    return pairs


def pull(h: Harness, note_id: int, **params: Any) -> Pulled:
    """Export one note and download its attachments, checking each against its sha256."""
    response = h.send("GET", f"/notes/{note_id}/export", params=params or None)
    where = f"GET /notes/{note_id}/export"
    h.expect_status(response, 200, where)
    kind = response.headers.get("content-type", "")
    need(
        kind.startswith("text/markdown"),
        f"{where} answered Content-Type {kind!r}, not text/markdown",
    )
    raw = response.headers.get("x-arp-attachments")
    if raw is None:  # R§7: a note with hundreds of embeds may not fit a header
        manifest = h.get_note(note_id)["attachments"]
    else:
        try:
            manifest = json.loads(raw)
        except ValueError as exc:
            raise CheckFailed(f"{where}: X-Arp-Attachments is not JSON: {raw[:120]!r}") from exc
    need(isinstance(manifest, list), f"{where}: X-Arp-Attachments must be a JSON list")
    files: dict[str, bytes] = {}
    for item in manifest:
        h.schemas.validate("Attachment", item, f"{where} X-Arp-Attachments entry")
        got = h.client.get(item["content_url"])
        h.expect_status(got, 200, f"download of {item['filename']}")
        same(
            sha256_hex(got.content), item["sha256"], f"sha256 of the downloaded {item['filename']}"
        )
        files[item["ref_in_markdown"]] = got.content
    return Pulled(
        text=response.content.decode("utf-8"),
        part=response.headers.get("x-arp-export-part", ""),
        attachments=manifest,
        files=files,
    )


def sync_back(
    h: Harness, pulled: Pulled, *, label: str, path: str, **over: Any
) -> tuple[int, dict[str, Any]]:
    """`arp-notes sync` of a pulled file: upsert its text and the sha256s of the files beside it."""
    entries = [
        {
            "sha256": sha256_hex(pulled.files[a["ref_in_markdown"]]),
            "filename": a["filename"],
            "mime": a["mime"],
            "size_bytes": len(pulled.files[a["ref_in_markdown"]]),
            "ref_in_markdown": a["ref_in_markdown"],
        }
        for a in pulled.attachments
    ]
    return h.upsert(
        h.fixture.doc("scratch"),
        label=label,
        body=pulled.text,
        path=path,
        attachments=entries,
        **over,
    )


# -- checks ---------------------------------------------------------------------------------


@check("export.disabled_is_refused")
def disabled_is_refused(h: Harness) -> None:
    note = h.create_note("Exported")
    if h.capabilities["export"]:
        raise CheckSkipped("the host allows export; only a host that disables it is tested here")
    h.fails("GET", f"/notes/{note['id']}/export", 403, "export_disabled")


@check("export.app_note_markdown")
def app_note_markdown(h: Harness) -> None:
    if not h.capabilities["export"]:
        raise CheckSkipped("the host declares export=false (see export.disabled_is_refused)")
    body = "# Written here\n\nSome text of my own.\n"
    note = h.create_note(
        "Written", body_md=body, person="Ann Other", note_date="2026-10-19", place="Studio B"
    )
    pulled = pull(h, note["id"])
    same(pulled.part, "note", "X-Arp-Export-Part of a plain export")
    pairs = frontmatter(pulled.text)
    need(bool(pairs.get("arp_id")), "an app note's export must open with an `arp_id` property")
    for name, value in (
        ("person", "Ann Other"),
        ("note_date", "2026-10-19"),
        ("place", "Studio B"),
    ):
        same(pairs.get(name), value, f"exported frontmatter `{name}`")
    same(pairs.get("kind"), note["kind"], "exported frontmatter `kind`")
    need("exported_at" in pairs, "an app note's export carries `exported_at`")
    need(
        pulled.text.endswith(body),
        "the exported Markdown must keep the stored body, unchanged, after the frontmatter",
    )
    same(pulled.attachments, [], "attachments of a note without any")
    again = pull(h, note["id"])
    same(frontmatter(again.text)["arp_id"], pairs["arp_id"], "arp_id across two exports")
    h.fails("GET", f"/notes/{UNKNOWN_ID}/export", 404, "not_found")
    h.fails(
        "GET",
        f"/notes/{note['id']}/export",
        REJECTED,
        params={"with_enrichment": "true", "enrichment_style": "no-such-style"},
    )


@check("export.round_trip_app_note")
def round_trip_app_note(h: Harness) -> None:
    if not h.capabilities["export"]:
        raise CheckSkipped("the host declares export=false")
    body = "# Round trip\n\nWritten in the app.\n\n- a list\n- of two\n"
    note = h.create_note("Round", body_md=body, person="Ann Other", note_date="2026-10-19")
    pulled = pull(h, note["id"])
    arp_id = frontmatter(pulled.text)["arp_id"]

    synced_id, created = sync_back(
        h, pulled, label="pulled", path="Pulled/Round trip.md", source_doc_id=arp_id
    )
    same(created["outcome"], "created", "first sync of a pulled folder")
    same(created["missing_attachments"], [], "missing_attachments")
    back = h.get_note(synced_id)
    same(back["body_md"].encode("utf-8"), pulled.text.encode("utf-8"), "body after sync, bytes")
    same(back["content_hash"], sha256_hex(pulled.text), "content_hash after sync")
    same(back["source_doc_id"], arp_id, "the synced note keeps the arp_id as its source id")

    _, again = sync_back(
        h, pulled, label="pulled", path="Pulled/Round trip.md", source_doc_id=arp_id
    )
    same(again["outcome"], "unchanged", "a second sync of the same pulled folder")

    repulled = pull(h, synced_id)
    same(repulled.text, pulled.text, "export of the synced copy is the same text (a fixpoint)")


@check("export.round_trip_attachments")
def round_trip_attachments(h: Harness) -> None:
    if not h.capabilities["export"]:
        raise CheckSkipped("the host declares export=false")
    attachments_on(h)
    blobs: list[Blob] = [new_blob(h, "first"), new_blob(h, "second")]
    for blob in blobs:
        upload(h, blob)
    note_id, made = upsert_with(h, "attached", blobs)
    same(made["missing_attachments"], [], "missing_attachments of the source note")
    original = h.get_note(note_id)

    pulled = pull(h, note_id)
    same(pulled.text.encode("utf-8"), original["body_md"].encode("utf-8"), "export of an import")
    same(
        sorted(a["sha256"] for a in pulled.attachments),
        sorted(b.sha256 for b in blobs),
        "sha256 of the exported attachments",
    )
    for blob in blobs:
        same(pulled.files.get(blob.filename), blob.data, f"downloaded bytes of {blob.filename}")

    _, synced = sync_back(h, pulled, label="attached", path="Scratch/attached.md")
    same(synced["outcome"], "unchanged", "sync of a pulled folder, outcome")
    same(synced["missing_attachments"], [], "sync of a pulled folder, missing_attachments")
    after = h.get_note(note_id)
    same(after["body_md"].encode("utf-8"), original["body_md"].encode("utf-8"), "body bytes")
    same(after["content_hash"], original["content_hash"], "content_hash")
    same(
        sorted(a["sha256"] for a in after["attachments"]),
        sorted(a["sha256"] for a in original["attachments"]),
        "attachment sha256s after the round trip",
    )


@check("export.enrichment_is_opt_in")
def enrichment_is_opt_in(h: Harness) -> None:
    if not h.capabilities["export"]:
        raise CheckSkipped("the host declares export=false")
    target = link_target(h)
    note_id, _ = h.upsert(h.fixture.doc("masterclass"))
    h.confirm(
        note_id,
        {
            "entity_type": target.entity_type,
            "entity_id": target.entity_id,
            "quote": "the passage",
            "comment": "worth keeping",
        },
    )
    plain = pull(h, note_id)
    need("arp_links" not in plain.text, "a plain export must not add enrichment (it is opt-in)")

    rich = pull(h, note_id, with_enrichment="true", enrichment_style="frontmatter")
    same(rich.part, "note", "X-Arp-Export-Part with frontmatter enrichment")
    need("arp_links:" in rich.text, "with_enrichment=true must add an `arp_links` property")
    need(
        re.search(rf"entity_id:\s*{target.entity_id}\b", rich.text) is not None,
        f"arp_links must name entity_id {target.entity_id}",
    )

    companion = pull(h, note_id, with_enrichment="true", enrichment_style="companion")
    same(companion.part, "companion", "X-Arp-Export-Part with companion enrichment")
    need("arp_links:" in companion.text, "the companion document must carry `arp_links`")
    need(
        "arp_companion_for" in frontmatter(companion.text),
        "the companion document must say what it is for (`arp_companion_for`)",
    )
