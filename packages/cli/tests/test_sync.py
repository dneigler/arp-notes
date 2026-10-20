"""`arp-notes sync`: id insert, upload-first, upsert, repair, rename, dry run (ga-mxal.36)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from arp_notes_cli.main import main
from cli_support import API, PNG_A, PNG_B, make_vault, sha, write
from sync_support import FakeHost

NOTE = """---
creation date: 2026-10-18 09:03
tags: [MeetingNote]
---
**Attendees**:: [[Roy Howat]]

# Op. 10
![[shot-1.png]]
"""


@pytest.fixture
def host(api: Any) -> FakeHost:
    return FakeHost(api)


def _sync(
    *args: str, capsys: pytest.CaptureFixture[str], app: bool = True
) -> tuple[int, dict[str, Any], str]:
    code = main(["sync", *args, "--app", "pt", "--json"])
    captured = capsys.readouterr()
    return code, json.loads(captured.out) if captured.out.strip() else {}, captured.err


def _vault_with_note(tmp_path: Path, text: str = NOTE) -> tuple[Path, Path]:
    vault = make_vault(tmp_path)
    note = write(vault, "Masterclasses/2026-10-18 Roy Howat.md", text)
    write(vault, "attachments/shot-1.png", PNG_A)
    return vault, note


# --- first sync ----------------------------------------------------------------------------


def test_first_sync_inserts_one_line_hashes_after_the_write_and_uploads_first(
    tmp_path: Path, config_home: Path, host: FakeHost, capsys: pytest.CaptureFixture[str]
) -> None:
    vault, note = _vault_with_note(tmp_path)
    original = note.read_bytes()

    code, result, _ = _sync(str(vault / "Masterclasses"), capsys=capsys)

    after = note.read_bytes()
    lines_after = after.decode().splitlines(keepends=True)
    assert code == 0 and result["errors"] == []
    # exactly one line added, right after the opening fence; everything else is untouched
    assert lines_after[0] == "---\n" and lines_after[1].startswith("arp_id: ")
    assert b"".join(line.encode() for i, line in enumerate(lines_after) if i != 1) == original
    arp_id = lines_after[1].removeprefix("arp_id: ").strip()
    # upload-url -> PUT -> upsert, in that order, one upsert
    names = [c for c in host.calls if "upload" in c or "upsert" in c]
    assert names == [
        "POST /attachments/upload-url",
        f"PUT /attachments/upload/ticket-{sha(PNG_A)[:12]}",
        "POST /notes/sync/upsert",
    ]
    (payload,) = host.upserts
    assert payload["source_doc_id"] == arp_id
    assert payload["content_hash"] == sha(after)  # hashed after the id line exists
    assert payload["body_md"] == after.decode()  # the whole file verbatim, frontmatter included
    assert payload["source_workspace"] == "Dave2025"
    assert payload["source_path"] == "Masterclasses/2026-10-18 Roy Howat.md"
    assert payload["title"] == "2026-10-18 Roy Howat"
    assert payload["note_date"] == "2026-10-18"
    assert payload["person"] == "Roy Howat"
    assert payload["kind"] == "meeting"
    assert payload["frontmatter"]["arp_id"] == arp_id
    assert payload["source_url"].startswith("obsidian://open?vault=Dave2025&file=Masterclasses%2F")
    assert payload["attachments"] == [
        {
            "sha256": sha(PNG_A),
            "filename": "shot-1.png",
            "mime": "image/png",
            "size_bytes": len(PNG_A),
            "ref_in_markdown": "![[shot-1.png]]",
        }
    ]
    assert result["synced"] == [
        {
            "path": "Masterclasses/2026-10-18 Roy Howat.md",
            "workspace": "Dave2025",
            "note_id": result["synced"][0]["note_id"],
            "outcome": "created",
            "uploaded": [sha(PNG_A)],
        }
    ]


def test_the_put_carries_content_type_and_length_and_no_bearer(
    tmp_path: Path, config_home: Path, host: FakeHost, capsys: pytest.CaptureFixture[str]
) -> None:
    vault, _ = _vault_with_note(tmp_path)

    _sync(str(vault / "Masterclasses"), capsys=capsys)

    (put,) = host.puts
    assert put.content == PNG_A
    assert put.headers["content-type"] == "image/png"
    assert put.headers["content-length"] == str(len(PNG_A))
    assert "authorization" not in put.headers


def test_identical_pair_uploads_once(
    tmp_path: Path, config_home: Path, host: FakeHost, capsys: pytest.CaptureFixture[str]
) -> None:
    vault = make_vault(tmp_path)
    write(vault, "n.md", "# Two views\n![[a.png]]\n![[copy/b.png]]\n")
    write(vault, "a.png", PNG_A)
    write(vault, "copy/b.png", PNG_A)  # same bytes, other name

    code, result, _ = _sync(str(vault / "n.md"), capsys=capsys)

    assert code == 0
    assert host.upload_url_calls() == 1 and host.put_calls() == 1
    assert result["synced"][0]["uploaded"] == [sha(PNG_A)]
    refs = [(a["ref_in_markdown"], a["filename"]) for a in host.upserts[0]["attachments"]]
    assert refs == [("![[a.png]]", "a.png"), ("![[copy/b.png]]", "b.png")]


def test_a_blob_the_host_already_has_is_not_sent(
    tmp_path: Path, config_home: Path, host: FakeHost, capsys: pytest.CaptureFixture[str]
) -> None:
    vault, _ = _vault_with_note(tmp_path)
    host.blobs[sha(PNG_A)] = PNG_A

    _, result, _ = _sync(str(vault / "Masterclasses"), capsys=capsys)

    assert host.upload_url_calls() == 1 and host.put_calls() == 0
    assert result["synced"][0]["uploaded"] == []


def test_same_image_in_two_notes_uploads_once_per_run(
    tmp_path: Path, config_home: Path, host: FakeHost, capsys: pytest.CaptureFixture[str]
) -> None:
    vault = make_vault(tmp_path)
    write(vault, "a.md", "![[p.png]]\n")
    write(vault, "b.md", "![[p.png]]\n")
    write(vault, "p.png", PNG_A)

    _, result, _ = _sync(str(vault / "a.md"), str(vault / "b.md"), capsys=capsys)

    assert host.put_calls() == 1
    assert sorted(len(i["uploaded"]) for i in result["synced"]) == [0, 1]


# --- second run, rename, repair ------------------------------------------------------------


def test_second_run_is_unchanged_with_zero_uploads_and_no_vault_write(
    tmp_path: Path, config_home: Path, host: FakeHost, capsys: pytest.CaptureFixture[str]
) -> None:
    vault, note = _vault_with_note(tmp_path)
    _sync(str(vault / "Masterclasses"), capsys=capsys)
    synced_bytes, mtime = note.read_bytes(), note.stat().st_mtime_ns
    host.calls.clear()
    host.puts.clear()

    code, result, _ = _sync(str(vault / "Masterclasses"), capsys=capsys)

    assert code == 0
    assert result["synced"][0]["outcome"] == "unchanged"
    assert result["synced"][0]["uploaded"] == []
    assert host.upload_url_calls() == 0 and host.put_calls() == 0
    assert note.read_bytes() == synced_bytes and note.stat().st_mtime_ns == mtime


def test_an_edit_resyncs_the_changed_note(
    tmp_path: Path, config_home: Path, host: FakeHost, capsys: pytest.CaptureFixture[str]
) -> None:
    vault, note = _vault_with_note(tmp_path)
    _sync(str(vault / "Masterclasses"), capsys=capsys)
    note.write_bytes(note.read_bytes() + b"\nOne more line.\n")

    _, result, _ = _sync(str(vault / "Masterclasses"), capsys=capsys)

    assert result["synced"][0]["outcome"] == "updated"
    assert host.upserts[-1]["content_hash"] == sha(note.read_bytes())
    assert host.put_calls() == 1  # the image was not sent again


def test_a_rename_keeps_the_arp_id_and_reports_the_old_path(
    tmp_path: Path, config_home: Path, host: FakeHost, capsys: pytest.CaptureFixture[str]
) -> None:
    vault, note = _vault_with_note(tmp_path)
    _, first, _ = _sync(str(vault / "Masterclasses"), capsys=capsys)
    moved = vault / "Archive" / "Howat.md"
    moved.parent.mkdir()
    note.rename(moved)
    host.puts.clear()

    code, result, _ = _sync(str(vault / "Archive"), capsys=capsys)

    assert code == 0
    assert host.upserts[-1]["source_doc_id"] == host.upserts[0]["source_doc_id"]
    assert host.upserts[-1]["source_path"] == "Archive/Howat.md"
    (item,) = result["synced"]
    assert item["note_id"] == first["synced"][0]["note_id"]
    assert item["renamed_from"] == "Masterclasses/2026-10-18 Roy Howat.md"
    assert host.put_calls() == 0


@pytest.mark.parametrize("as_409", [False, True])
def test_missing_attachments_are_uploaded_then_reupserted_once(
    tmp_path: Path, config_home: Path, api: Any, as_409: bool, capsys: pytest.CaptureFixture[str]
) -> None:
    host = FakeHost(api, missing_as_409=as_409, lose_blobs_once=True)
    vault, _ = _vault_with_note(tmp_path)

    code, result, _ = _sync(str(vault / "Masterclasses"), capsys=capsys)

    assert code == 0, result
    assert len(host.upserts) == 2 and host.upserts[0] == host.upserts[1]
    assert host.put_calls() == 2  # sent, "lost" by the host, sent again after the report
    assert result["synced"][0]["uploaded"] == [sha(PNG_A), sha(PNG_A)]


def test_still_missing_after_the_second_upsert_is_an_error(
    tmp_path: Path, config_home: Path, api: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    host = FakeHost(api)
    host.blobs = _AmnesiacBlobs()
    vault, _ = _vault_with_note(tmp_path)

    code, result, _ = _sync(str(vault / "Masterclasses"), capsys=capsys)

    assert code == 1 and len(host.upserts) == 2
    assert "still lacks attachments" in result["errors"][0]["error"]


class _AmnesiacBlobs(dict[str, bytes]):
    def __contains__(self, key: object) -> bool:
        return False


# --- dry run, no-write-id, kind ------------------------------------------------------------


def test_dry_run_changes_nothing_anywhere(
    tmp_path: Path, config_home: Path, host: FakeHost, capsys: pytest.CaptureFixture[str]
) -> None:
    vault, note = _vault_with_note(tmp_path)
    before, mtime = note.read_bytes(), note.stat().st_mtime_ns

    code, result, _ = _sync(str(vault / "Masterclasses"), "--dry-run", capsys=capsys)

    assert code == 0
    assert note.read_bytes() == before and note.stat().st_mtime_ns == mtime
    assert [p.name for p in note.parent.iterdir()] == [note.name]  # no temp file left behind
    assert set(host.calls) <= {"GET /notes/capabilities", "GET /notes/sync/manifest"}
    (item,) = result["synced"]
    assert item["outcome"] == "would_create" and item["would_write_id"] is True
    assert item["would_upload"] == [sha(PNG_A)] and item["uploaded"] == []


def test_dry_run_of_a_synced_note_says_unchanged_or_would_update(
    tmp_path: Path, config_home: Path, host: FakeHost, capsys: pytest.CaptureFixture[str]
) -> None:
    vault, note = _vault_with_note(tmp_path)
    _sync(str(vault / "Masterclasses"), capsys=capsys)
    _, same, _ = _sync(str(vault / "Masterclasses"), "--dry-run", capsys=capsys)
    note.write_bytes(note.read_bytes() + b"edit\n")
    _, edited, _ = _sync(str(vault / "Masterclasses"), "--dry-run", capsys=capsys)

    assert same["synced"][0]["outcome"] == "unchanged"
    assert edited["synced"][0]["outcome"] == "would_update"
    assert edited["synced"][0]["would_upload"] == []


def test_no_write_id_leaves_the_vault_alone_and_uses_the_path(
    tmp_path: Path, config_home: Path, host: FakeHost, capsys: pytest.CaptureFixture[str]
) -> None:
    vault, note = _vault_with_note(tmp_path)
    before = note.read_bytes()

    code, result, err = _sync(str(vault / "Masterclasses"), "--no-write-id", capsys=capsys)

    assert code == 0 and note.read_bytes() == before
    (payload,) = host.upserts
    assert payload["source_doc_id"] == "Masterclasses/2026-10-18 Roy Howat.md"
    assert payload["content_hash"] == sha(before)
    assert "renaming" in result["warnings"][0]["warning"]
    # and the second run recognises it by that path
    _, again, _ = _sync(str(vault / "Masterclasses"), "--no-write-id", capsys=capsys)
    assert again["synced"][0]["outcome"] == "unchanged"


def test_kind_flag_overrides_the_guess(
    tmp_path: Path, config_home: Path, host: FakeHost, capsys: pytest.CaptureFixture[str]
) -> None:
    vault, _ = _vault_with_note(tmp_path)

    _sync(str(vault / "Masterclasses"), "--kind", "masterclass", capsys=capsys)

    assert host.upserts[0]["kind"] == "masterclass"


# --- verify --------------------------------------------------------------------------------


def test_sync_verify_passes_when_the_host_holds_the_bytes(
    tmp_path: Path, config_home: Path, host: FakeHost, capsys: pytest.CaptureFixture[str]
) -> None:
    vault, _ = _vault_with_note(tmp_path)

    code, result, _ = _sync(str(vault / "Masterclasses"), "--verify", capsys=capsys)

    assert code == 0 and result["synced"][0]["verified"] is True
    assert host.calls[-1].startswith("GET /notes/")


def test_sync_verify_fails_loudly_on_a_paraphrased_body(
    tmp_path: Path, config_home: Path, host: FakeHost, capsys: pytest.CaptureFixture[str]
) -> None:
    vault, _ = _vault_with_note(tmp_path)
    host.tamper_body = "# Op. 10\n(summary of the note)\n"

    code, result, _ = _sync(str(vault / "Masterclasses"), "--verify", capsys=capsys)

    assert code == 1
    assert result["synced"][0]["verified"] is False
    assert "body differs from the local file at byte" in result["errors"][0]["error"]


# --- failures ------------------------------------------------------------------------------


def test_one_failing_note_does_not_stop_the_others_and_the_exit_is_non_zero(
    tmp_path: Path, config_home: Path, host: FakeHost, capsys: pytest.CaptureFixture[str]
) -> None:
    vault = make_vault(tmp_path)
    write(vault, "a.md", "first\n")
    write(vault, "b.md", "second\n")
    write(vault, "c.md", "third\n")
    host.fail_upsert_for.add("b.md")

    code, result, _ = _sync(
        str(vault / "a.md"), str(vault / "b.md"), str(vault / "c.md"), capsys=capsys
    )

    assert code == 1
    assert [i["path"] for i in result["synced"]] == ["a.md", "c.md"]
    assert result["errors"][0]["path"] == "b.md" and "HTTP 500" in result["errors"][0]["error"]


def test_a_rejected_token_stops_the_run_and_marks_the_rest_not_attempted(
    tmp_path: Path, config_home: Path, api: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    import httpx

    host = FakeHost(api)
    api.post(f"{API}/notes/sync/upsert").mock(
        return_value=httpx.Response(401, json={"error": "no"})
    )
    vault = make_vault(tmp_path)
    write(vault, "a.md", "first\n")
    write(vault, "b.md", "second\n")

    code, result, _ = _sync(str(vault / "a.md"), str(vault / "b.md"), capsys=capsys)

    assert code == 1 and host.upserts == []
    assert [e["path"] for e in result["errors"]] == ["a.md", "b.md"]
    assert result["errors"][1]["error"].startswith("not attempted")


def test_a_copied_note_with_a_duplicate_arp_id_is_refused(
    tmp_path: Path, config_home: Path, host: FakeHost, capsys: pytest.CaptureFixture[str]
) -> None:
    vault = make_vault(tmp_path)
    write(vault, "a.md", "---\narp_id: same\n---\nx\n")
    write(vault, "copy of a.md", "---\narp_id: same\n---\nx\n")
    write(vault, "other.md", "fresh\n")

    code, result, _ = _sync(
        str(vault / "a.md"), str(vault / "copy of a.md"), str(vault / "other.md"), capsys=capsys
    )

    assert code == 1
    assert [i["path"] for i in result["synced"]] == ["other.md"]
    assert {e["path"] for e in result["errors"]} == {"a.md", "copy of a.md"}


def test_a_host_without_attachments_gets_the_note_and_a_warning(
    tmp_path: Path, config_home: Path, api: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    host = FakeHost(api, attachments=False)
    vault, _ = _vault_with_note(tmp_path)

    code, result, _ = _sync(str(vault / "Masterclasses"), capsys=capsys)

    assert code == 0 and host.upload_url_calls() == 0
    assert host.upserts[0]["attachments"] == []
    assert "does not accept attachments" in result["warnings"][0]["warning"]


def test_unresolved_embeds_are_reported_but_do_not_fail_the_sync(
    tmp_path: Path, config_home: Path, host: FakeHost, capsys: pytest.CaptureFixture[str]
) -> None:
    vault = make_vault(tmp_path)
    write(vault, "n.md", "![[nowhere.png]]\n")

    code, result, _ = _sync(str(vault / "n.md"), capsys=capsys)

    assert code == 0
    assert result["synced"][0]["unresolved_embeds"] == ["![[nowhere.png]]"]


def test_a_vault_root_is_refused_before_anything_is_sent(
    tmp_path: Path, config_home: Path, host: FakeHost, capsys: pytest.CaptureFixture[str]
) -> None:
    vault = make_vault(tmp_path)

    code = main(["sync", str(vault), "--app", "pt"])

    assert code == 2 and host.calls == []
    assert "vault root" in capsys.readouterr().err


def test_an_empty_arp_id_key_is_an_error_for_that_note_only(
    tmp_path: Path, config_home: Path, host: FakeHost, capsys: pytest.CaptureFixture[str]
) -> None:
    vault = make_vault(tmp_path)
    bad = write(vault, "bad.md", "---\narp_id:\n---\nx\n")
    write(vault, "ok.md", "y\n")

    code, result, _ = _sync(str(vault / "bad.md"), str(vault / "ok.md"), capsys=capsys)

    assert code == 1 and bad.read_text() == "---\narp_id:\n---\nx\n"
    assert [i["path"] for i in result["synced"]] == ["ok.md"]
    assert "no value" in result["errors"][0]["error"]


def _edit_after_scan(monkeypatch: pytest.MonkeyPatch, edit: Any) -> None:
    """Run `edit()` right after the CLI has scanned, as if the user saved in Obsidian."""
    from arp_notes_cli import scan, sync

    real = scan.scan_vault_notes

    def scanned_then_edited(paths: Any) -> Any:
        found = real(paths)
        edit()
        return found

    monkeypatch.setattr(sync, "scan_vault_notes", scanned_then_edited)


def test_a_note_saved_between_scan_and_write_is_not_overwritten(
    tmp_path: Path,
    config_home: Path,
    host: FakeHost,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    vault, note = _vault_with_note(tmp_path)
    edited = NOTE + "typed just now\n"
    _edit_after_scan(monkeypatch, lambda: note.write_text(edited))

    code, result, _ = _sync(str(vault / "Masterclasses"), capsys=capsys)

    assert code == 1 and note.read_text() == edited and host.upserts == []
    assert "changed after it was scanned" in result["errors"][0]["error"]


def test_an_attachment_replaced_between_scan_and_upload_is_not_sent_under_the_old_hash(
    tmp_path: Path,
    config_home: Path,
    host: FakeHost,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    vault, _ = _vault_with_note(tmp_path)
    shot = vault / "attachments" / "shot-1.png"
    _edit_after_scan(monkeypatch, lambda: shot.write_bytes(PNG_B))

    code, result, _ = _sync(str(vault / "Masterclasses"), capsys=capsys)

    assert code == 1 and host.puts == [] and host.upserts == []
    assert "changed while syncing" in result["errors"][0]["error"]
