"""`arp-notes scan`: vault detection, embed resolution, hashes, manifest diff (CLI-a, ga-mxal.6)."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import httpx
import pytest
from arp_notes_cli.main import main
from arp_notes_cli.scan import find_embeds, read_arp_id, split_frontmatter
from cli_support import (
    API,
    PNG_A,
    PNG_B,
    make_vault,
    manifest_page,
    manifest_row,
    serve_manifest,
    sha,
    write,
)

MASTERCLASS = """---
arp_id: mc-1
title: Synthetic masterclass
meeting date: 2026-10-18
tags: [piano, "#pt"]
created: <% tp.date.now("YYYY-MM-DD") %>
---
Attendees:: [[Roy Howat]]
duration:: 25

# Opening
![[shot-1.png|300]]
Second view of the same screenshot: ![[shot-2.png]]
A phone photo: ![the page](images/pic%20three.png)
Remote images are not vault files: ![logo](https://example.com/logo.png)
A transcluded note is not an attachment: ![[Other note]]
Not a real embed, shown as code: `![[inline.png]]`

```md
![[fenced.png]]
```

Broken: ![[missing.png]]
"""


def _synthetic_vault(tmp_path: Path) -> Path:
    vault = make_vault(tmp_path)
    write(vault, "Masterclasses/2026-10-18 Synthetic masterclass.md", MASTERCLASS)
    write(vault, "attachments/shot-1.png", PNG_A)
    write(vault, "Masterclasses/img/shot-2.png", PNG_A)  # identical bytes, other name and folder
    write(vault, "deep/er/folder/shot-1.png", PNG_B)  # same name, longer path: must lose
    write(vault, "Masterclasses/images/pic three.png", PNG_B)
    write(vault, "Other note.md", "# Other\n")
    return vault


def _scan(*args: str, capsys: pytest.CaptureFixture[str]) -> tuple[int, dict[str, Any], str]:
    code = main(["scan", *args, "--app", "pt", "--json"])
    captured = capsys.readouterr()
    return code, json.loads(captured.out) if captured.out.strip() else {}, captured.err


def _paths(result: dict[str, Any], bucket: str) -> list[str]:
    return [item["path"] for item in result[bucket]]


# --- the five buckets ---------------------------------------------------------------------


def test_buckets(
    tmp_path: Path, config_home: Path, api: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    vault = make_vault(tmp_path)
    same = "---\narp_id: s1\n---\nunchanged\n"
    changed_old = "---\narp_id: c1\n---\nold text\n"
    moved = "---\narp_id: r1\n---\nmoved, same bytes\n"
    moved_old = "---\narp_id: r2\n---\nmoved, then edited (old)\n"
    write(vault, "Meetings/new.md", "no id yet\n")
    write(vault, "Meetings/unknown-id.md", "---\narp_id: zzz\n---\nserver never saw this id\n")
    write(vault, "Meetings/same.md", same)
    write(vault, "Meetings/changed.md", "---\narp_id: c1\n---\nnew text\n")
    write(vault, "Meetings/moved.md", moved)
    write(vault, "Meetings/moved-edited.md", "---\narp_id: r2\n---\nmoved, then edited (new)\n")
    write(vault, "Meetings/ignored.txt", "not markdown, inside the folder\n")
    route = serve_manifest(
        api,
        [
            manifest_row("s1", "Meetings/same.md", same.encode()),
            manifest_row("c1", "Meetings/changed.md", changed_old.encode()),
            manifest_row("r1", "Old/moved.md", moved.encode()),
            manifest_row("r2", "Old/moved-edited.md", moved_old.encode()),
            manifest_row("d1", "Meetings/gone.md", b"deleted from disk"),
            manifest_row(
                "d2", "Meetings/already-tombstoned.md", b"x", deleted_at="2026-10-01T00:00:00"
            ),
            manifest_row("o1", "Elsewhere/not-in-scope.md", b"outside the scanned folder"),
        ],
    )

    code, result, _ = _scan(str(vault / "Meetings"), capsys=capsys)

    assert code == 0
    assert sorted(_paths(result, "new")) == ["Meetings/new.md", "Meetings/unknown-id.md"]
    assert _paths(result, "changed") == ["Meetings/changed.md"]
    assert _paths(result, "unchanged") == ["Meetings/same.md"]
    renamed = {item["path"]: item for item in result["renamed"]}
    assert set(renamed) == {"Meetings/moved.md", "Meetings/moved-edited.md"}
    assert renamed["Meetings/moved.md"]["old_path"] == "Old/moved.md"
    assert renamed["Meetings/moved.md"]["content_changed"] is False
    assert renamed["Meetings/moved-edited.md"]["content_changed"] is True
    # Only a live row inside the scanned scope whose file is gone counts as deleted.
    assert result["deleted"] == [
        {
            "path": "Meetings/gone.md",
            "workspace": "Dave2025",
            "arp_id": "d1",
            "last_synced_at": "2026-10-18T14:30:00",
        }
    ]
    assert result["errors"] == []
    assert route.calls.last.request.url.params["source_workspace"] == "Dave2025"
    assert route.calls.last.request.url.params["source_system"] == "obsidian"
    assert route.calls.last.request.headers["authorization"] == "Bearer pt_test_token"


def test_content_hash_is_sha256_of_the_exact_file_bytes(
    tmp_path: Path, config_home: Path, api: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    vault = make_vault(tmp_path)
    raw = (
        b"---\r\narp_id: crlf-1\r\n---\r\nWindows line endings \xe2\x80\x94 and a BOM-less body\r\n"
    )
    write(vault, "a.md", raw)
    serve_manifest(api, [manifest_row("crlf-1", "a.md", raw)])

    code, result, _ = _scan(str(vault / "a.md"), capsys=capsys)

    assert code == 0
    assert result["unchanged"][0]["content_hash"] == sha(raw)
    assert result["unchanged"][0]["size_bytes"] == len(raw)


def test_attachment_set_difference_marks_a_note_changed(
    tmp_path: Path, config_home: Path, api: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    vault = make_vault(tmp_path)
    note = "---\narp_id: p1\n---\n![[pic.png]]\n"
    write(vault, "n.md", note)
    write(vault, "pic.png", PNG_B)  # the image was replaced after the last sync
    serve_manifest(api, [manifest_row("p1", "n.md", note.encode(), [PNG_A])])

    code, result, _ = _scan(str(vault / "n.md"), capsys=capsys)

    assert code == 0
    assert _paths(result, "changed") == ["n.md"]


def test_tombstoned_note_whose_file_is_back_needs_a_sync(
    tmp_path: Path, config_home: Path, api: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    vault = make_vault(tmp_path)
    note = "---\narp_id: t1\n---\nback again\n"
    write(vault, "n.md", note)
    serve_manifest(
        api, [manifest_row("t1", "n.md", note.encode(), deleted_at="2026-10-02T00:00:00")]
    )

    _, result, _ = _scan(str(vault / "n.md"), capsys=capsys)

    assert _paths(result, "changed") == ["n.md"]
    assert result["deleted"] == []


def test_two_files_with_one_arp_id_are_an_error_not_a_guess(
    tmp_path: Path, config_home: Path, api: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    vault = make_vault(tmp_path)
    write(vault, "a.md", "---\narp_id: dup\n---\none\n")
    write(vault, "copy of a.md", "---\narp_id: dup\n---\none\n")
    write(vault, "b.md", "plain\n")
    serve_manifest(api, [])

    code, result, _ = _scan(
        str(vault / "a.md"), str(vault / "copy of a.md"), str(vault / "b.md"), capsys=capsys
    )
    assert code == 1
    assert _paths(result, "new") == ["b.md"]
    assert sorted(e["path"] for e in result["errors"]) == ["a.md", "copy of a.md"]
    assert "duplicate arp_id dup" in result["errors"][0]["error"]


# --- explicit scope (D2) ------------------------------------------------------------------


def test_vault_root_is_refused_and_nothing_is_fetched(
    tmp_path: Path, config_home: Path, api: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    vault = _synthetic_vault(tmp_path)
    route = serve_manifest(api, [])

    code = main(["scan", str(vault), "--app", "pt"])

    err = capsys.readouterr().err
    assert code == 2
    assert "vault root" in err and ".obsidian" in err and "whole vault" in err
    assert not route.called


def test_vault_root_is_refused_even_next_to_valid_paths(
    tmp_path: Path, config_home: Path, api: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    vault = _synthetic_vault(tmp_path)
    route = serve_manifest(api, [])

    code = main(["scan", str(vault / "Masterclasses"), str(vault), "--app", "pt"])

    assert code == 2
    assert not route.called


def test_refusals_need_no_configured_app(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("ARP_NOTES_CONFIG_DIR", str(tmp_path / "empty"))
    vault = _synthetic_vault(tmp_path)

    assert main(["scan", str(vault), "--app", "pt"]) == 2

    assert "vault root" in capsys.readouterr().err


def test_path_outside_any_vault_is_refused(
    tmp_path: Path, config_home: Path, api: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    loose = write(tmp_path / "loose", "n.md", "no vault here\n")

    code = main(["scan", str(loose), "--app", "pt"])

    assert code == 2
    assert "not inside an Obsidian vault" in capsys.readouterr().err


def test_missing_path_is_refused(
    tmp_path: Path, config_home: Path, api: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    code = main(["scan", str(tmp_path / "nope.md"), "--app", "pt"])
    assert code == 2
    assert "no such file or folder" in capsys.readouterr().err


def test_a_folder_inside_the_vault_is_scanned_and_dot_folders_are_skipped(
    tmp_path: Path, config_home: Path, api: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    vault = _synthetic_vault(tmp_path)
    write(vault, "Masterclasses/.trash/old.md", "deleted in Obsidian\n")
    serve_manifest(api, [])

    _, result, _ = _scan(str(vault / "Masterclasses"), capsys=capsys)

    assert _paths(result, "new") == ["Masterclasses/2026-10-18 Synthetic masterclass.md"]


def test_scan_writes_nothing(
    tmp_path: Path, config_home: Path, api: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    vault = _synthetic_vault(tmp_path)
    serve_manifest(api, [])

    def snapshot() -> dict[str, tuple[bytes, int]]:
        return {
            str(p): (p.read_bytes(), p.stat().st_mtime_ns) for p in vault.rglob("*") if p.is_file()
        }

    before = snapshot()
    _scan(str(vault / "Masterclasses"), capsys=capsys)
    assert snapshot() == before
    # The id line D1 would add is `sync`'s job, not scan's.
    assert "arp_id" not in (vault / "Other note.md").read_text()


# --- embeds and hashes --------------------------------------------------------------------


def test_synthetic_vault_embeds(
    tmp_path: Path, config_home: Path, api: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    vault = _synthetic_vault(tmp_path)
    serve_manifest(api, [])

    _, result, _ = _scan(str(vault / "Masterclasses"), capsys=capsys)

    (note,) = result["new"]
    assert note["arp_id"] == "mc-1"
    assert note["workspace"] == "Dave2025"
    by_ref = {a["ref"]: a for a in note["attachments"]}
    assert list(by_ref) == [
        "![[shot-1.png|300]]",  # the exact text, size suffix included
        "![[shot-2.png]]",
        "![the page](images/pic%20three.png)",
    ]
    # Shortest path wins over deep/er/folder/shot-1.png, which has different bytes.
    assert by_ref["![[shot-1.png|300]]"]["path"] == "attachments/shot-1.png"
    assert by_ref["![[shot-1.png|300]]"]["sha256"] == sha(PNG_A)
    # The identical-image pair: two refs, two paths, one hash.
    assert by_ref["![[shot-2.png]]"]["path"] == "Masterclasses/img/shot-2.png"
    assert by_ref["![[shot-2.png]]"]["sha256"] == sha(PNG_A)
    # A standard Markdown link is relative to the note and URL-decoded.
    assert by_ref["![the page](images/pic%20three.png)"]["path"] == (
        "Masterclasses/images/pic three.png"
    )
    assert by_ref["![the page](images/pic%20three.png)"]["sha256"] == sha(PNG_B)
    assert note["unresolved_embeds"] == ["![[missing.png]]"]


def test_identical_images_with_one_manifest_hash_are_unchanged(
    tmp_path: Path, config_home: Path, api: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    vault = _synthetic_vault(tmp_path)
    serve_manifest(
        api,
        [
            manifest_row(
                "mc-1",
                "Masterclasses/2026-10-18 Synthetic masterclass.md",
                MASTERCLASS.encode(),
                [PNG_A, PNG_A, PNG_B],  # the server holds one blob per distinct hash
            )
        ],
    )

    _, result, _ = _scan(str(vault / "Masterclasses"), capsys=capsys)

    assert _paths(result, "unchanged") == ["Masterclasses/2026-10-18 Synthetic masterclass.md"]


def test_wiki_embed_with_a_folder_matches_the_path_suffix(
    tmp_path: Path, config_home: Path, api: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    vault = make_vault(tmp_path)
    write(vault, "n.md", "![[b/pic.png]] ![[Pic.PNG]]\n")
    write(vault, "a/pic.png", PNG_A)
    write(vault, "x/b/pic.png", PNG_B)
    write(vault, "pic.png", PNG_A)
    serve_manifest(api, [])

    _, result, _ = _scan(str(vault / "n.md"), capsys=capsys)

    paths = {a["ref"]: a["path"] for a in result["new"][0]["attachments"]}
    assert paths["![[b/pic.png]]"] == "x/b/pic.png"
    assert paths["![[Pic.PNG]]"] == "pic.png"  # case-insensitive fallback, still shortest


def test_find_embeds_ignores_code_urls_notes_and_other_extensions() -> None:
    body = (
        "![[a.png]] ![[a.png]] ![[Note]] ![[Note.md]] ![[sheet.csv]] ![[#Heading]]\n"
        "![[clip.mp3|alias]] ![[doc.pdf#page=3]] ![x](<my pic.jpg>) ![y](http://h/z.png)\n"
        "`![[no.png]]`\n~~~\n![[fenced.png]]\n~~~\n"
    )
    assert [(e.ref, e.target, e.kind) for e in find_embeds(body)] == [
        ("![[a.png]]", "a.png", "wiki"),
        ("![[clip.mp3|alias]]", "clip.mp3", "wiki"),
        ("![[doc.pdf#page=3]]", "doc.pdf", "wiki"),
        ("![x](<my pic.jpg>)", "my pic.jpg", "markdown"),
    ]


# --- frontmatter (read only) --------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("---\narp_id: abc-123\n---\nbody", "abc-123"),
        ('---\narp_id: "abc-123"\n---\nbody', "abc-123"),
        ("---\r\nkey with spaces: x\r\narp_id: abc\r\n---\r\nbody", "abc"),
        ("---\narp_id:abc\n---\n", "abc"),
        ("---\narp_id:   \n---\n", None),
        ("---\n  arp_id: nested\n---\n", None),
        ("---\ntitle: t\n---\narp_id: in-the-body\n", None),
        ("arp_id: not frontmatter\n", None),
        ("---\narp_id: never closed\n", None),
        ("﻿---\narp_id: bom\n---\n", "bom"),
    ],
)
def test_read_arp_id(text: str, expected: str | None) -> None:
    assert read_arp_id(text) == expected


def test_split_frontmatter_keeps_dataview_and_templater_in_the_body() -> None:
    block, body = split_frontmatter(MASTERCLASS)
    assert block is not None and "meeting date: 2026-10-18" in block
    assert body.startswith("Attendees:: [[Roy Howat]]")


# --- output and failures ------------------------------------------------------------------


def test_human_output(
    tmp_path: Path, config_home: Path, api: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    vault = _synthetic_vault(tmp_path)
    serve_manifest(api, [])

    code = main(["scan", str(vault / "Masterclasses"), "--app", "pt"])

    out = capsys.readouterr().out
    assert code == 0
    assert "new (1)" in out and "changed (0)" in out
    assert "Dave2025: Masterclasses/2026-10-18 Synthetic masterclass.md" in out
    assert "[1 unresolved embed(s)]" in out


def test_two_vaults_are_diffed_against_their_own_manifests(
    tmp_path: Path, config_home: Path, api: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    one = make_vault(tmp_path, "One")
    two = make_vault(tmp_path, "Two")
    text = "---\narp_id: shared-looking\n---\nbody\n"
    write(one, "n.md", text)
    write(two, "n.md", text)

    def manifest(request: httpx.Request) -> httpx.Response:
        rows = (
            [manifest_row("shared-looking", "n.md", text.encode())]
            if request.url.params["source_workspace"] == "One"
            else []
        )
        return httpx.Response(200, json=manifest_page(rows))

    api.get(f"{API}/notes/sync/manifest").mock(side_effect=manifest)

    _, result, _ = _scan(str(one / "n.md"), str(two / "n.md"), capsys=capsys)

    assert [(i["workspace"], i["path"]) for i in result["unchanged"]] == [("One", "n.md")]
    assert [(i["workspace"], i["path"]) for i in result["new"]] == [("Two", "n.md")]


def test_manifest_is_read_across_pages(
    tmp_path: Path, config_home: Path, api: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    vault = make_vault(tmp_path)
    text = "---\narp_id: late\n---\nbody\n"
    write(vault, "n.md", text)
    pages = {
        None: manifest_page([manifest_row("early", "x.md", b"x")], next_after="early"),
        "early": manifest_page([manifest_row("late", "n.md", text.encode())]),
    }
    route = api.get(f"{API}/notes/sync/manifest").mock(
        side_effect=lambda request: httpx.Response(200, json=pages[request.url.params.get("after")])
    )

    _, result, _ = _scan(str(vault / "n.md"), capsys=capsys)

    assert _paths(result, "unchanged") == ["n.md"]
    assert route.call_count == 2
    assert route.calls[0].request.url.params["limit"] == "500"


def test_a_host_speaking_protocol_2_is_refused(
    tmp_path: Path, config_home: Path, api: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    vault = make_vault(tmp_path)
    write(vault, "n.md", "x\n")
    api.get(f"{API}/notes/sync/manifest").mock(
        return_value=httpx.Response(200, json={"protocol": 2, "items": []})
    )

    code = main(["scan", str(vault / "n.md"), "--app", "pt"])

    assert code == 1
    assert "protocol" in capsys.readouterr().err


def test_unknown_app_and_missing_token(
    tmp_path: Path,
    config_home: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    vault = make_vault(tmp_path)
    note = write(vault, "n.md", "x\n")

    assert main(["scan", str(note), "--app", "nope"]) == 2
    assert "unknown app 'nope'" in capsys.readouterr().err

    monkeypatch.delenv("ARP_NOTES_TOKEN")
    monkeypatch.setitem(sys.modules, "keyring", None)  # no keyring either
    assert main(["scan", str(note), "--app", "pt"]) == 1
    assert "no API token" in capsys.readouterr().err
