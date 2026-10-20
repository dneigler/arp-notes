"""export.py and GET /notes/{id}/export (ADR §3.7, C3 ga-mxal.10)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import pytest
from app_ref import API, BOB, ORIGIN, Ref, fails, ok
from arp_notes import export, sync
from repo_support import USER, add_blob, add_link, add_note, attachment_ref, upsert_body

NOW = datetime(2026, 10, 19, 12, 30, 5, tzinfo=UTC)
STAMP = "2026-10-19T12:30:05Z"


@pytest.fixture(autouse=True)
def fixed_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(export, "_now", lambda: NOW)


def create(ref: Ref, **body: object) -> int:
    made = ref.post("/notes", json={"title": "Class", **body})
    return ok(made, "Note", 201)["id"]


def get_export(ref: Ref, note_id: int, **params: str):  # noqa: ANN201
    return ref.get(f"/notes/{note_id}/export", params=params)


# -- app-authored notes ---------------------------------------------------------------------


def test_an_app_note_exports_with_frontmatter(ref: Ref) -> None:
    note_id = create(
        ref,
        body_md="# Etudes\n\nSlowly.\n",
        kind="masterclass",
        person="Ana Lima",
        note_date="2026-10-18",
        place="Studio 2",
    )
    response = get_export(ref, note_id)
    assert response.status_code == 200
    assert response.headers["content-type"] == "text/markdown; charset=utf-8"
    assert response.headers["x-arp-export-part"] == "note"
    head, _, body = response.text.partition("\n---\n")
    arp_id = head.splitlines()[1]
    assert arp_id.startswith("arp_id: ") and len(arp_id) == len("arp_id: ") + 36
    assert head.splitlines()[2:] == [
        "kind: masterclass",
        'person: "Ana Lima"',
        "note_date: 2026-10-18",
        'place: "Studio 2"',
        f"exported_at: {STAMP}",
    ]
    assert head.startswith("---\n") and body == "# Etudes\n\nSlowly.\n"


def test_empty_fields_are_left_out_and_the_arp_id_is_stable(ref: Ref) -> None:
    note_id = create(ref, body_md="text")
    first = get_export(ref, note_id).text
    assert (
        first
        == f"---\narp_id: {first.splitlines()[1][8:]}\nkind: note\nexported_at: {STAMP}\n---\ntext"
    )
    assert get_export(ref, note_id).text == first
    other = create(ref, body_md="text")
    assert get_export(ref, other).text.splitlines()[1] != first.splitlines()[1]


def test_unsafe_scalars_are_quoted(ref: Ref) -> None:
    note_id = create(ref, kind="no", person='Roy: the "first" one', place="Zürich #2")
    lines = get_export(ref, note_id).text.splitlines()
    assert 'kind: "no"' in lines
    assert 'person: "Roy: the \\"first\\" one"' in lines
    assert 'place: "Zürich #2"' in lines


def test_an_app_note_with_its_own_frontmatter_gets_one_block(ref: Ref) -> None:
    note_id = create(ref, body_md="---\ntitle: Mine\nkind: keep-me\n---\nBody\n", kind="lecture")
    text = get_export(ref, note_id).text
    assert text.count("---\n") == 2
    lines = text.splitlines()
    assert lines[0] == "---" and lines[lines.index("title: Mine") + 1] == "kind: keep-me"
    assert lines.count("kind: lecture") == 0  # the user's own kind wins, never duplicated
    assert any(line.startswith("arp_id: ") for line in lines[:4])
    assert text.endswith("---\nBody\n")


def test_crlf_frontmatter_stays_crlf(ref: Ref) -> None:
    note_id = create(ref, body_md="---\r\ntitle: Mine\r\n---\r\nBody\r\n")
    text = get_export(ref, note_id).text
    assert "\n" not in text.replace("\r\n", "")
    assert text.startswith("---\r\narp_id: ") and text.endswith("title: Mine\r\n---\r\nBody\r\n")


def test_an_unclosed_frontmatter_fence_is_just_body(ref: Ref) -> None:
    note_id = create(ref, body_md="---\nnot closed\n")
    text = get_export(ref, note_id).text
    assert text.endswith("---\n---\nnot closed\n")


# -- imported notes -------------------------------------------------------------------------


IMPORTED = "---\narp_id: 4f6c0d2e-1111-4222-8333-944455556666\ntags: [a]\n---\n# Class\n\nBody.\n"


def imported(ref: Ref, body: str = IMPORTED, **over: Any) -> int:
    result = sync.upsert(
        ref.cfg, USER, upsert_body("4f6c0d2e-1111-4222-8333-944455556666", body, **over)
    )
    return result.note_id


def test_an_imported_note_exports_its_stored_body_verbatim(ref: Ref) -> None:
    note_id = imported(ref)
    response = get_export(ref, note_id)
    assert response.text == IMPORTED
    assert response.headers["x-arp-export-part"] == "note"


def test_an_imported_note_without_frontmatter_is_not_touched(ref: Ref) -> None:
    note_id = imported(ref, "plain body\n")
    assert get_export(ref, note_id).text == "plain body\n"


def test_a_tombstoned_note_still_exports(ref: Ref) -> None:
    note_id = imported(ref)
    sync.tombstone(ref.cfg, USER, "obsidian", "Vault", ["4f6c0d2e-1111-4222-8333-944455556666"])
    assert get_export(ref, note_id).text == IMPORTED


# -- enrichment -----------------------------------------------------------------------------


def linked_note(ref: Ref) -> int:
    note_id = add_note(ref.db, title="Class", body_md="# Etudes\n\nText.\n", origin="app")
    add_link(
        ref.db,
        note_id,
        "movement",
        103,
        anchor="etudes",
        quote="Op. 10 nº 3",
        comment="Loose wrist",
        action_item="slow, hands apart\nmetronome 60",
        confidence=0.9,
    )
    add_link(ref.db, note_id, "composer", 1)
    add_link(ref.db, note_id, "technique", 7, status="rejected")
    return note_id


def test_enrichment_is_off_by_default(ref: Ref) -> None:
    text = get_export(ref, linked_note(ref)).text
    assert "arp_links" not in text and "arp_takeaways" not in text


def test_enrichment_as_frontmatter_properties(ref: Ref) -> None:
    text = get_export(ref, linked_note(ref), with_enrichment="true").text
    assert text.endswith("---\n# Etudes\n\nText.\n")
    block = text.split("\n---\n")[0]
    assert block.splitlines()[-1] != "arp_actions: []"
    assert (
        "arp_links:\n"
        "  - entity_type: movement\n"
        "    entity_id: 103\n"
        '    entity_label: "Op.10 nº 3"\n'
        "    anchor: etudes\n"
        '    quote: "Op. 10 nº 3"\n'
        "    confidence: 0.9\n"
        "  - entity_type: composer\n"
        "    entity_id: 1\n"
        "    entity_label: Chopin\n"
    ) in block
    assert 'arp_takeaways:\n  - anchor: etudes\n    comment: "Loose wrist"\n' in block
    assert (
        "arp_actions:\n"
        '  - text: "slow, hands apart"\n'
        "    anchor: etudes\n"
        "    entity_type: movement\n"
        "    entity_id: 103\n"
        "    completed: false\n"
        '  - text: "metronome 60"\n'
    ) in block
    assert "technique" not in block  # rejected links are not exported


def test_enrichment_with_no_links_writes_empty_lists(ref: Ref) -> None:
    note_id = create(ref, body_md="x")
    block = get_export(ref, note_id, with_enrichment="true").text.split("\n---\n")[0]
    assert "arp_links: []" in block and "arp_takeaways: []" in block and "arp_actions: []" in block


def test_enrichment_in_an_imported_notes_existing_frontmatter(ref: Ref) -> None:
    note_id = imported(ref)
    add_link(ref.db, note_id, "composer", 1)
    text = get_export(ref, note_id, with_enrichment="true").text
    assert text.startswith("---\narp_links:\n  - entity_type: composer\n")
    assert "arp_id: 4f6c0d2e-1111-4222-8333-944455556666\ntags: [a]\n---\n# Class" in text
    assert text.count("arp_id:") == 1  # an imported note adds nothing but the enrichment


def test_enrichment_never_overwrites_a_key_the_user_already_has(ref: Ref) -> None:
    body = "---\narp_links: mine\n---\nx\n"
    note_id = imported(ref, body)
    add_link(ref.db, note_id, "composer", 1)
    text = get_export(ref, note_id, with_enrichment="true").text
    assert text.count("arp_links") == 1 and "arp_links: mine" in text


def test_enrichment_as_a_companion_document(ref: Ref) -> None:
    note_id = linked_note(ref)
    plain = get_export(ref, note_id, with_enrichment="true", enrichment_style="companion")
    assert plain.headers["x-arp-export-part"] == "companion"
    text = plain.text
    assert text.startswith("---\narp_id: ") and "arp_companion_for: Class\n" in text
    assert f"exported_at: {STAMP}\n" in text and "arp_links:\n  - entity_type: movement" in text
    assert "# Etudes" not in text
    note = get_export(ref, note_id, enrichment_style="companion")  # opt-in: off means the note
    assert note.headers["x-arp-export-part"] == "note" and note.text.endswith("# Etudes\n\nText.\n")


def test_an_unknown_style_is_422(ref: Ref) -> None:
    note_id = create(ref)
    assert get_export(ref, note_id, enrichment_style="sidecar").status_code == 422
    with pytest.raises(export.InvalidEnrichmentStyle):
        export.export_note(ref.cfg, USER, note_id, True, "sidecar")


# -- manifest header ------------------------------------------------------------------------


def test_the_attachment_manifest_rides_in_a_header(ref: Ref) -> None:
    blob_id, digest = add_blob(ref.db, text="pic")
    result = sync.upsert(
        ref.cfg,
        USER,
        upsert_body("d1", attachments=[attachment_ref(digest, "![[ünï.webp]]", "ünï.webp")]),
    )
    response = get_export(ref, result.note_id)
    raw = response.headers["x-arp-attachments"]
    assert raw.isascii() and "\n" not in raw
    manifest = json.loads(raw)
    assert len(manifest) == 1
    row = manifest[0]
    assert row["filename"] == "ünï.webp" and row["ref_in_markdown"] == "![[ünï.webp]]"
    assert row["sha256"] == digest and row["blob_id"] == blob_id and row["mime"] == "image/webp"
    assert row["content_url"].startswith(f"{ORIGIN}{API}/attachments/{blob_id}/content?exp=")
    assert response.text == "# Intro\n\ntext\n"  # embeds stay as stored; pull rewrites them


def test_a_note_without_attachments_has_an_empty_manifest(ref: Ref) -> None:
    assert json.loads(get_export(ref, create(ref)).headers["x-arp-attachments"]) == []


# -- policy and ownership -------------------------------------------------------------------


def test_export_off_is_403(ref: Ref) -> None:
    note_id = create(ref)
    off = ref.with_policy(export=False)
    assert fails(get_export(off, note_id), 403, "export_disabled")["error"] == "export_disabled"
    with pytest.raises(export.ExportDisabled):
        export.export_note(off.cfg, USER, note_id)


def test_export_is_404_for_another_users_note(ref: Ref) -> None:
    note_id = create(ref)
    fails(ref.get(f"/notes/{note_id}/export", headers=BOB), 404, "not_found")
    fails(ref.get("/notes/999/export"), 404, "not_found")
