"""`arp-notes verify` and `arp-notes tombstone` (CLI-b, ga-mxal.36)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from arp_notes_cli.main import main
from cli_support import API, PNG_A, make_vault, write
from sync_support import FakeHost


def _run(*argv: str, capsys: pytest.CaptureFixture[str]) -> tuple[int, dict[str, Any], str]:
    code = main([*argv, "--app", "pt", "--json"])
    captured = capsys.readouterr()
    return code, json.loads(captured.out) if captured.out.strip() else {}, captured.err


def _synced_vault(
    tmp_path: Path, api: Any, capsys: pytest.CaptureFixture[str]
) -> tuple[Path, Path, FakeHost]:
    host = FakeHost(api)
    vault = make_vault(tmp_path)
    note = write(vault, "Meetings/roy.md", "# Roy\n![[p.png]]\n")
    write(vault, "p.png", PNG_A)
    assert main(["sync", str(vault / "Meetings"), "--app", "pt", "--json"]) == 0
    capsys.readouterr()
    return vault, note, host


def _arp_id(note: Path) -> str:
    return note.read_text().splitlines()[1].removeprefix("arp_id: ")


# --- verify --------------------------------------------------------------------------------


def test_verify_passes_for_a_synced_note_and_only_reads(
    tmp_path: Path, config_home: Path, api: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    vault, note, host = _synced_vault(tmp_path, api, capsys)
    host.calls.clear()

    code, result, _ = _run("verify", str(vault / "Meetings"), capsys=capsys)

    assert code == 0 and result["errors"] == []
    (item,) = result["verified"]
    assert item["path"] == "Meetings/roy.md"
    assert item["note_id"] == host.notes[_arp_id(note)]["id"]
    assert all(call.startswith("GET ") for call in host.calls)


def test_verify_reports_a_body_the_host_changed(
    tmp_path: Path, config_home: Path, api: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    vault, note, host = _synced_vault(tmp_path, api, capsys)
    host.tamper_body = note.read_text().replace("Roy", "Roi")

    code, result, _ = _run("verify", str(vault / "Meetings"), capsys=capsys)

    assert code == 1 and result["verified"] == []
    assert "body differs from the local file at byte" in result["errors"][0]["error"]


def test_verify_reports_a_local_edit_that_was_never_synced(
    tmp_path: Path, config_home: Path, api: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    vault, note, _ = _synced_vault(tmp_path, api, capsys)
    note.write_text(note.read_text() + "edited after the sync\n")

    code, result, _ = _run("verify", str(vault / "Meetings"), capsys=capsys)

    error = result["errors"][0]["error"]
    assert code == 1 and "content_hash mismatch" in error and "body differs" in error


def test_verify_reports_unsynced_and_unknown_notes(
    tmp_path: Path, config_home: Path, api: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    vault, _, _ = _synced_vault(tmp_path, api, capsys)
    write(vault, "Meetings/new.md", "never synced\n")
    write(vault, "Meetings/stranger.md", "---\narp_id: not-on-host\n---\nx\n")

    code, result, _ = _run("verify", str(vault / "Meetings"), capsys=capsys)

    errors = {e["path"]: e["error"] for e in result["errors"]}
    assert code == 1
    assert "never synced" in errors["Meetings/new.md"]
    assert "no note with this arp_id" in errors["Meetings/stranger.md"]
    assert [v["path"] for v in result["verified"]] == ["Meetings/roy.md"]


# --- tombstone -----------------------------------------------------------------------------


def test_tombstone_finds_the_workspace_through_the_manifests(
    tmp_path: Path, config_home: Path, api: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    _, note, host = _synced_vault(tmp_path, api, capsys)
    arp_id = _arp_id(note)

    code, result, _ = _run("tombstone", arp_id, capsys=capsys)

    assert code == 0 and result == {"tombstoned": 1, "unknown": []}
    assert host.notes[arp_id]["deleted_at"]
    sent = next(c for c in api.calls if c.request.url.path.endswith("/tombstone")).request
    assert json.loads(sent.content) == {
        "source_system": "obsidian",
        "source_workspace": "Dave2025",
        "source_doc_ids": [arp_id],
    }


def test_tombstone_with_an_explicit_workspace_skips_the_lookup(
    tmp_path: Path, config_home: Path, api: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    _, note, host = _synced_vault(tmp_path, api, capsys)
    host.calls.clear()

    code, result, _ = _run("tombstone", _arp_id(note), "--workspace", "Dave2025", capsys=capsys)

    assert code == 0 and result["tombstoned"] == 1
    assert host.calls == ["POST /notes/sync/tombstone"]


def test_tombstone_reports_unknown_ids_and_exits_non_zero(
    tmp_path: Path, config_home: Path, api: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    _, note, _ = _synced_vault(tmp_path, api, capsys)

    code, result, _ = _run("tombstone", _arp_id(note), "typo-id", "typo-id", capsys=capsys)

    assert code == 1
    assert result == {"tombstoned": 1, "unknown": ["typo-id"]}


def test_tombstone_of_only_unknown_ids_sends_nothing(
    tmp_path: Path, config_home: Path, api: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    _, _, host = _synced_vault(tmp_path, api, capsys)
    host.calls.clear()

    code, result, _ = _run("tombstone", "nope", capsys=capsys)

    assert code == 1 and result == {"tombstoned": 0, "unknown": ["nope"]}
    assert "POST /notes/sync/tombstone" not in host.calls


def test_tombstone_without_sync_sources_asks_for_a_workspace(
    config_home: Path, api: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    api.get(f"{API}/notes").mock(return_value=httpx.Response(200, json={"items": []}))

    code = main(["tombstone", "abc", "--app", "pt"])

    assert code == 1 and "pass --workspace" in capsys.readouterr().err
