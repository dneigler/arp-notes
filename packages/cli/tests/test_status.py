"""`arp-notes status`: last sync per path from the manifest (CLI-a, ga-mxal.6)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from arp_notes_cli.main import main
from cli_support import API, manifest_page, manifest_row


def _serve(api: Any, per_workspace: dict[str, list[dict[str, Any]]]) -> None:
    api.get(f"{API}/notes/sync/manifest").mock(
        side_effect=lambda request: httpx.Response(
            200, json=manifest_page(per_workspace[request.url.params["source_workspace"]])
        )
    )


def test_status_for_a_named_workspace_sorts_by_path(
    config_home: Path, api: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    _serve(
        api,
        {
            "Dave2025": [
                manifest_row("b", "Z/last.md", b"b"),
                manifest_row("a", "A/first.md", b"a", deleted_at="2026-10-02T00:00:00"),
            ]
        },
    )

    code = main(["status", "--app", "pt", "--workspace", "Dave2025", "--json"])

    report = json.loads(capsys.readouterr().out)["sources"]
    assert code == 0
    assert report == [
        {
            "source_system": "obsidian",
            "source_workspace": "Dave2025",
            "notes": [
                {
                    "path": "A/first.md",
                    "arp_id": "a",
                    "last_synced_at": "2026-10-18T14:30:00",
                    "deleted_at": "2026-10-02T00:00:00",
                },
                {
                    "path": "Z/last.md",
                    "arp_id": "b",
                    "last_synced_at": "2026-10-18T14:30:00",
                    "deleted_at": None,
                },
            ],
        }
    ]


def test_status_without_workspace_uses_the_hosts_sync_sources(
    config_home: Path, api: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    api.get(f"{API}/notes").mock(
        return_value=httpx.Response(
            200,
            json={
                "items": [],
                "sync_sources": [
                    {
                        "source_system": "obsidian",
                        "source_workspace": "Dave2025",
                        "last_synced_at": "2026-10-18T14:30:00",
                        "note_count": 1,
                    },
                    {
                        "source_system": "obsidian",
                        "source_workspace": "Work",
                        "last_synced_at": "2026-10-17T09:00:00",
                        "note_count": 0,
                    },
                ],
            },
        )
    )
    _serve(api, {"Dave2025": [manifest_row("a", "a.md", b"a")], "Work": []})

    code = main(["status", "--app", "pt"])

    out = capsys.readouterr().out
    assert code == 0
    assert "obsidian “Dave2025” (1 notes)" in out
    assert "  a.md  synced  last sync 2026-10-18T14:30:00" in out
    assert "obsidian “Work” (0 notes)" in out


def test_status_marks_source_deleted_notes(
    config_home: Path, api: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    _serve(api, {"V": [manifest_row("a", "a.md", b"a", deleted_at="2026-10-02T00:00:00")]})

    main(["status", "--app", "pt", "--workspace", "V"])

    assert "a.md  source deleted 2026-10-02T00:00:00" in capsys.readouterr().out


def test_status_with_nothing_synced(
    config_home: Path, api: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    api.get(f"{API}/notes").mock(
        return_value=httpx.Response(200, json={"items": [], "sync_sources": []})
    )

    assert main(["status", "--app", "pt"]) == 0
    assert "nothing synced yet" in capsys.readouterr().out
