"""`arp-notes pull`: export to Markdown + attachments, never overwrite, round trip (ga-mxal.37)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from arp_notes_cli.main import main
from arp_notes_cli.pull import (
    comparable,
    replace_refs,
    rewrite_ref,
    safe_attachment_name,
    safe_stem,
)
from cli_support import PNG_A, PNG_B, make_vault, sha, write
from pull_support import ExportHost

APP_BODY = "Played it for Roy.\n\n![First shot](attachment://11)\n\n![Second](attachment://12)\n"
APP_ATTACHMENTS = [
    ("shot one.png", PNG_A, "![First shot](attachment://11)"),
    ("shot2.png", PNG_B, "![Second](attachment://12)"),
]


@pytest.fixture
def host(api: Any) -> ExportHost:
    return ExportHost(api)


def _pull(*args: str, capsys: pytest.CaptureFixture[str]) -> tuple[int, dict[str, Any], str]:
    code = main(["pull", *args, "--app", "pt", "--json"])
    captured = capsys.readouterr()
    return code, json.loads(captured.out) if captured.out.strip() else {}, captured.err


def _cli(command: str, *args: str, capsys: pytest.CaptureFixture[str]) -> dict[str, Any]:
    code = main([command, *args, "--app", "pt", "--json"])
    out = json.loads(capsys.readouterr().out)
    assert code == 0, out
    return out


def _app_note(host: ExportHost, title: str = "Op 10 notes", **kwargs: Any) -> int:
    return host.add_app_note(title, kwargs.pop("body", APP_BODY), APP_ATTACHMENTS, **kwargs)


# --- the pieces ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("ref", "filename", "expected"),
    [
        ("![[shot.png]]", "shot.png", "![[shot.png]]"),  # already resolves beside the note
        ("![[Attachments/shot.png|300]]", "shot.png", "![[shot.png|300]]"),
        ("![[shot.png#top|438x282]]", "other.png", "![[other.png#top|438x282]]"),
        ("![shot](attachment://7)", "shot.png", "![shot](shot.png)"),
        ("![](images/a.png)", "a.png", "![](a.png)"),
        ('![alt](x/a.png "A title")', "a.png", '![alt](a.png "A title")'),
        ("![](<my dir/a b.png>)", "a b.png", "![](a%20b.png)"),
        ("![](a%20b.png)", "a b.png", "![](a%20b.png)"),  # already pointing at it
        ("![](./a.png)", "a.png", "![](./a.png)"),
        ("![](attachment://9)", "x (1).png", "![](x%20%281%29.png)"),
        ("[a recording](attachment://3)", "take.mp3", "[a recording](take.mp3)"),
        ("<img src='attachment://3'>", "a.png", None),  # a form we do not know
    ],
)
def test_rewrite_ref_keeps_syntax_alias_and_size(
    ref: str, filename: str, expected: str | None
) -> None:
    assert rewrite_ref(ref, filename) == expected


def test_replace_refs_leaves_code_alone_and_edits_every_use() -> None:
    text = (
        "![a](attachment://1) and again ![a](attachment://1)\n"
        "`![a](attachment://1)` inline\n"
        "```md\n![a](attachment://1)\n```\n"
    )
    out = replace_refs(text, {"![a](attachment://1)": "![a](a.png)"})
    assert out == (
        "![a](a.png) and again ![a](a.png)\n"
        "`![a](attachment://1)` inline\n"
        "```md\n![a](attachment://1)\n```\n"
    )


def test_names_are_made_safe_without_losing_the_extension() -> None:
    assert safe_stem("Q: what/why? #1 [draft]", "x") == "Q- what-why- -1 -draft-"
    assert safe_stem("  ..  ", "Untitled") == "Untitled"
    assert safe_attachment_name("../../etc/passwd") == ("passwd", "")
    assert safe_attachment_name("dir\\shot 1.PNG") == ("shot 1", ".PNG")
    assert safe_attachment_name("....png") == ("attachment", ".png")


def test_comparable_drops_only_exported_at() -> None:
    a = "---\narp_id: 1\nexported_at: 2026-10-19T12:00:01Z\n---\nbody exported_at: x\n"
    b = "---\narp_id: 1\nexported_at: 2026-10-19T12:09:59Z\n---\nbody exported_at: x\n"
    assert comparable(a) == comparable(b)
    assert comparable(a) != comparable(b.replace("body", "other"))


# --- an app-authored note ------------------------------------------------------------------


def test_pulls_an_app_note_with_its_attachments_beside_it_and_embeds_rewritten(
    tmp_path: Path, config_home: Path, host: ExportHost, capsys: pytest.CaptureFixture[str]
) -> None:
    note_id = _app_note(host)
    folder = tmp_path / "out"

    code, result, err = _pull("--all-app-notes", "--to", str(folder), capsys=capsys)

    assert code == 0 and result["errors"] == [], err
    (item,) = result["pulled"]
    assert item["outcome"] == "created" and item["note_id"] == note_id
    assert item["arp_id"] == host.arp_id_of(note_id)
    assert item["path"] == "Op 10 notes.md"
    text = (folder / "Op 10 notes.md").read_text(encoding="utf-8")
    assert text.startswith(f"---\narp_id: {host.arp_id_of(note_id)}\n")
    assert "![First shot](shot%20one.png)" in text and "![Second](shot2.png)" in text
    assert "attachment://" not in text
    assert (folder / "shot one.png").read_bytes() == PNG_A
    assert (folder / "shot2.png").read_bytes() == PNG_B
    assert [(a["path"], a["sha256"], a["outcome"]) for a in item["attachments"]] == [
        ("shot one.png", sha(PNG_A), "created"),
        ("shot2.png", sha(PNG_B), "created"),
    ]
    assert not [p for p in folder.iterdir() if p.name.endswith(".tmp")]
    # the Bearer goes to the API, never to the signed download
    assert all(r.headers["authorization"] == "Bearer pt_test_token" for r in host.exports)
    assert len(host.downloads) == 2
    assert all("authorization" not in r.headers for r in host.downloads)


def test_an_absolute_content_url_works_too(
    tmp_path: Path, config_home: Path, api: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    host = ExportHost(api, absolute_urls=True)
    _app_note(host)
    code, result, err = _pull("--all-app-notes", "--to", str(tmp_path / "out"), capsys=capsys)
    assert code == 0 and result["errors"] == [], err
    assert len(host.downloads) == 2


def test_without_the_header_the_notes_own_attachments_are_used(
    tmp_path: Path, config_home: Path, api: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    host = ExportHost(api, omit_header=True)
    note_id = _app_note(host)
    folder = tmp_path / "out"

    code, result, err = _pull(str(note_id), "--to", str(folder), capsys=capsys)

    assert code == 0 and result["errors"] == [], err
    assert (folder / "shot one.png").read_bytes() == PNG_A
    assert f"GET /notes/{note_id}" in host.calls


def test_a_note_is_pulled_by_numeric_id_and_a_missing_one_is_reported_not_fatal(
    tmp_path: Path, config_home: Path, host: ExportHost, capsys: pytest.CaptureFixture[str]
) -> None:
    good = _app_note(host)

    code, result, err = _pull("9999", str(good), "--to", str(tmp_path / "out"), capsys=capsys)

    assert code == 1
    assert [i["note_id"] for i in result["pulled"]] == [good]
    assert result["errors"][0]["id"] == "9999" and "404" in result["errors"][0]["error"]


def test_the_same_image_embedded_twice_is_one_file_and_one_download(
    tmp_path: Path, config_home: Path, host: ExportHost, capsys: pytest.CaptureFixture[str]
) -> None:
    host.add_app_note(
        "Twice",
        "![[a.png]] small ![[a.png|300]]\n",
        [("a.png", PNG_A, "![[a.png]]"), ("a.png", PNG_A, "![[a.png|300]]")],
    )
    folder = tmp_path / "out"

    code, result, _ = _pull("--all-app-notes", "--to", str(folder), capsys=capsys)

    assert code == 0
    assert sorted(p.name for p in folder.glob("*.png")) == ["a.png"]
    assert len(host.downloads) == 1
    assert [a["path"] for a in result["pulled"][0]["attachments"]] == ["a.png"]
    assert "![[a.png]] small ![[a.png|300]]" in (folder / "Twice.md").read_text(encoding="utf-8")


def test_an_embed_inside_code_is_not_rewritten(
    tmp_path: Path, config_home: Path, host: ExportHost, capsys: pytest.CaptureFixture[str]
) -> None:
    ref = "![shot](attachment://1)"
    host.add_app_note("Doc", f"{ref}\n\n`{ref}`\n", [("shot.png", PNG_A, ref)])
    folder = tmp_path / "out"

    _pull("--all-app-notes", "--to", str(folder), capsys=capsys)

    body = (folder / "Doc.md").read_text(encoding="utf-8").split("---\n", 2)[2]
    assert body == f"![shot](shot.png)\n\n`{ref}`\n"


# --- an imported note ----------------------------------------------------------------------

IMPORTED = """---
tags: [MeetingNote]
---
**Attendees**:: [[Roy Howat]]

![[shot-1.png|438x282]]
"""


def _synced_vault(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], root: str = "a"
) -> tuple[Path, Path, str]:
    """A vault with one note synced to the host: (vault, note file, its arp_id)."""
    vault = make_vault(tmp_path / root)
    note = write(vault, "Masterclasses/2026-10-18 Roy Howat.md", IMPORTED)
    write(vault, "attachments/shot-1.png", PNG_A)
    _cli("sync", str(vault / "Masterclasses"), capsys=capsys)
    arp_id = next(
        line.removeprefix("arp_id: ")
        for line in note.read_text(encoding="utf-8").splitlines()
        if line.startswith("arp_id: ")
    )
    return vault, note, arp_id


def test_an_imported_note_comes_back_verbatim_by_arp_id(
    tmp_path: Path, config_home: Path, host: ExportHost, capsys: pytest.CaptureFixture[str]
) -> None:
    _, note, arp_id = _synced_vault(tmp_path, capsys)
    folder = tmp_path / "out"

    code, result, err = _pull(arp_id, "--to", str(folder), capsys=capsys)

    assert code == 0 and result["errors"] == [], err
    assert (folder / "2026-10-18 Roy Howat.md").read_bytes() == note.read_bytes()
    assert (folder / "shot-1.png").read_bytes() == PNG_A


def test_an_unknown_arp_id_is_an_error_and_the_rest_still_pull(
    tmp_path: Path, config_home: Path, host: ExportHost, capsys: pytest.CaptureFixture[str]
) -> None:
    _, _, arp_id = _synced_vault(tmp_path, capsys)

    code, result, _ = _pull("not-an-id", arp_id, "--to", str(tmp_path / "out"), capsys=capsys)

    assert code == 1
    assert len(result["pulled"]) == 1
    assert result["errors"][0]["id"] == "not-an-id"
    assert "unknown arp_id" in result["errors"][0]["error"]


# --- never overwrite -----------------------------------------------------------------------


def test_pulling_again_changes_nothing_even_though_exported_at_moved(
    tmp_path: Path, config_home: Path, host: ExportHost, capsys: pytest.CaptureFixture[str]
) -> None:
    _app_note(host)
    folder = tmp_path / "out"
    _pull("--all-app-notes", "--to", str(folder), capsys=capsys)
    first = (folder / "Op 10 notes.md").read_bytes()
    stamp = (folder / "Op 10 notes.md").stat().st_mtime_ns
    downloads = len(host.downloads)

    code, result, _ = _pull("--all-app-notes", "--to", str(folder), capsys=capsys)

    assert code == 0
    assert result["pulled"][0]["outcome"] == "unchanged"
    assert {a["outcome"] for a in result["pulled"][0]["attachments"]} == {"unchanged"}
    assert (folder / "Op 10 notes.md").read_bytes() == first  # the first stamp stays
    assert (folder / "Op 10 notes.md").stat().st_mtime_ns == stamp
    assert len(host.downloads) == downloads
    assert host.export_count == 2


def test_a_pulled_note_that_differs_is_refused_until_force(
    tmp_path: Path, config_home: Path, host: ExportHost, capsys: pytest.CaptureFixture[str]
) -> None:
    _app_note(host)
    folder = tmp_path / "out"
    _pull("--all-app-notes", "--to", str(folder), capsys=capsys)
    path = folder / "Op 10 notes.md"
    path.write_text(path.read_text(encoding="utf-8") + "\nmy own line\n", encoding="utf-8")
    edited = path.read_bytes()

    code, result, _ = _pull("--all-app-notes", "--to", str(folder), capsys=capsys)

    assert code == 1 and result["pulled"] == []
    assert "--force" in result["errors"][0]["error"]
    assert path.read_bytes() == edited

    code, result, _ = _pull("--all-app-notes", "--to", str(folder), "--force", capsys=capsys)

    assert code == 0 and result["pulled"][0]["outcome"] == "updated"
    assert b"my own line" not in path.read_bytes()


def test_a_refused_note_writes_nothing_not_even_its_attachments(
    tmp_path: Path, config_home: Path, host: ExportHost, capsys: pytest.CaptureFixture[str]
) -> None:
    _app_note(host)
    folder = tmp_path / "out"
    _pull("--all-app-notes", "--to", str(folder), capsys=capsys)
    (folder / "shot2.png").unlink()
    path = folder / "Op 10 notes.md"
    path.write_text(path.read_text(encoding="utf-8") + "edit\n", encoding="utf-8")
    downloads = len(host.downloads)

    code, _, _ = _pull("--all-app-notes", "--to", str(folder), capsys=capsys)

    assert code == 1
    assert not (folder / "shot2.png").exists()
    assert len(host.downloads) == downloads


def test_a_file_of_yours_with_the_same_name_is_left_alone(
    tmp_path: Path, config_home: Path, host: ExportHost, capsys: pytest.CaptureFixture[str]
) -> None:
    _app_note(host)
    folder = tmp_path / "out"
    mine = write(folder, "Op 10 notes.md", "my own notes, no arp_id\n")

    code, result, _ = _pull("--all-app-notes", "--to", str(folder), "--force", capsys=capsys)

    assert code == 0
    assert result["pulled"][0]["path"] == "Op 10 notes (2).md"
    assert mine.read_text(encoding="utf-8") == "my own notes, no arp_id\n"


def test_two_notes_with_one_title_get_two_files(
    tmp_path: Path, config_home: Path, host: ExportHost, capsys: pytest.CaptureFixture[str]
) -> None:
    host.add_app_note("Lesson", "first\n")
    host.add_app_note("Lesson", "second\n")
    folder = tmp_path / "out"

    code, result, _ = _pull("--all-app-notes", "--to", str(folder), capsys=capsys)

    assert code == 0
    assert [p["path"] for p in result["pulled"]] == ["Lesson.md", "Lesson (2).md"]
    assert "second" in (folder / "Lesson (2).md").read_text(encoding="utf-8")


def test_a_note_renamed_in_the_app_updates_the_file_it_already_has(
    tmp_path: Path, config_home: Path, host: ExportHost, capsys: pytest.CaptureFixture[str]
) -> None:
    note_id = _app_note(host)
    folder = tmp_path / "out"
    _pull("--all-app-notes", "--to", str(folder), capsys=capsys)
    host.app_notes[note_id]["title"] = "A new title"

    code, result, _ = _pull("--all-app-notes", "--to", str(folder), capsys=capsys)

    assert code == 0
    assert result["pulled"][0]["path"] == "Op 10 notes.md"  # same arp_id, same file
    assert sorted(p.name for p in folder.glob("*.md")) == ["Op 10 notes.md"]


def test_an_attachment_name_taken_by_other_bytes_is_numbered_even_with_force(
    tmp_path: Path, config_home: Path, host: ExportHost, capsys: pytest.CaptureFixture[str]
) -> None:
    host.add_app_note(
        "Shot", "![x](attachment://1)\n", [("shot.png", PNG_A, "![x](attachment://1)")]
    )
    folder = tmp_path / "out"
    theirs = write(folder, "shot.png", b"somebody else's picture")

    code, result, _ = _pull("--all-app-notes", "--to", str(folder), "--force", capsys=capsys)

    assert code == 0
    assert theirs.read_bytes() == b"somebody else's picture"
    assert (folder / "shot (2).png").read_bytes() == PNG_A
    assert "![x](shot%20%282%29.png)" in (folder / "Shot.md").read_text(encoding="utf-8")
    assert result["pulled"][0]["attachments"][0]["path"] == "shot (2).png"


def test_an_attachment_already_there_with_the_right_bytes_is_reused(
    tmp_path: Path, config_home: Path, host: ExportHost, capsys: pytest.CaptureFixture[str]
) -> None:
    _app_note(host)
    folder = tmp_path / "out"
    write(folder, "shot one.png", PNG_A)

    code, result, _ = _pull("--all-app-notes", "--to", str(folder), capsys=capsys)

    assert code == 0
    assert [a["outcome"] for a in result["pulled"][0]["attachments"]] == ["unchanged", "created"]
    assert len(host.downloads) == 1


def test_a_download_whose_bytes_do_not_hash_is_not_kept_and_the_note_is_not_written(
    tmp_path: Path, config_home: Path, host: ExportHost, capsys: pytest.CaptureFixture[str]
) -> None:
    _app_note(host)
    host.corrupt.add(sha(PNG_B))
    folder = tmp_path / "out"

    code, result, _ = _pull("--all-app-notes", "--to", str(folder), capsys=capsys)

    assert code == 1 and "sha256" in result["errors"][0]["error"]
    assert not (folder / "Op 10 notes.md").exists()
    assert not (folder / "shot2.png").exists()
    assert not [p for p in folder.iterdir() if p.name.endswith(".tmp")]


# --- enrichment ----------------------------------------------------------------------------


def test_enrichment_in_frontmatter_is_one_request_with_the_style(
    tmp_path: Path, config_home: Path, host: ExportHost, capsys: pytest.CaptureFixture[str]
) -> None:
    _app_note(host)
    folder = tmp_path / "out"

    code, _, _ = _pull("--all-app-notes", "--to", str(folder), "--with-enrichment", capsys=capsys)

    assert code == 0
    (request,) = host.exports
    assert dict(request.url.params) == {
        "with_enrichment": "true",
        "enrichment_style": "frontmatter",
    }
    assert "arp_links: []" in (folder / "Op 10 notes.md").read_text(encoding="utf-8")


def test_without_enrichment_no_enrichment_is_asked_for(
    tmp_path: Path, config_home: Path, host: ExportHost, capsys: pytest.CaptureFixture[str]
) -> None:
    _app_note(host)
    _pull("--all-app-notes", "--to", str(tmp_path / "out"), capsys=capsys)
    assert dict(host.exports[0].url.params) == {}


def test_a_companion_is_a_second_request_written_beside_the_note(
    tmp_path: Path, config_home: Path, host: ExportHost, capsys: pytest.CaptureFixture[str]
) -> None:
    note_id = _app_note(host)
    folder = tmp_path / "out"

    code, result, _ = _pull(
        "--all-app-notes",
        "--to", str(folder),
        "--with-enrichment", "--enrichment-style", "companion",
        capsys=capsys,
    )  # fmt: skip

    assert code == 0
    assert [dict(r.url.params) for r in host.exports] == [
        {},
        {"with_enrichment": "true", "enrichment_style": "companion"},
    ]
    assert result["pulled"][0]["companion"] == {"path": "Op 10 notes.arp.md", "outcome": "created"}
    note = (folder / "Op 10 notes.md").read_text(encoding="utf-8")
    companion = (folder / "Op 10 notes.arp.md").read_text(encoding="utf-8")
    assert "arp_links" not in note  # the note itself is left as it was
    assert "arp_companion_for: Op 10 notes" in companion and "arp_links: []" in companion

    # a second pull neither duplicates the note (the companion is not indexed as one) nor rewrites
    code, again, _ = _pull(
        "--all-app-notes",
        "--to", str(folder),
        "--with-enrichment", "--enrichment-style", "companion",
        capsys=capsys,
    )  # fmt: skip
    assert code == 0
    assert again["pulled"][0]["outcome"] == "unchanged"
    assert again["pulled"][0]["companion"]["outcome"] == "unchanged"
    assert sorted(p.name for p in folder.glob("*.md")) == ["Op 10 notes.arp.md", "Op 10 notes.md"]
    assert note_id in {r["note_id"] for r in again["pulled"]}


def test_a_pulled_companion_is_not_a_note_to_scan(
    tmp_path: Path, config_home: Path, host: ExportHost, capsys: pytest.CaptureFixture[str]
) -> None:
    _app_note(host)
    vault = make_vault(tmp_path)
    folder = vault / "From Practice Tracker"
    _pull(
        "--all-app-notes",
        "--to", str(folder),
        "--with-enrichment", "--enrichment-style", "companion",
        capsys=capsys,
    )  # fmt: skip
    assert (folder / "Op 10 notes.arp.md").exists()  # the companion carries the note's own arp_id

    scanned = _cli("scan", str(folder), capsys=capsys)

    assert scanned["errors"] == []
    listed = [
        n["path"] for bucket in ("new", "changed", "renamed", "unchanged") for n in scanned[bucket]
    ]
    assert listed == ["From Practice Tracker/Op 10 notes.md"]


# --- refusals ------------------------------------------------------------------------------


def test_nothing_named_is_a_usage_error(
    tmp_path: Path, config_home: Path, host: ExportHost, capsys: pytest.CaptureFixture[str]
) -> None:
    code, _, err = _pull("--to", str(tmp_path / "out"), capsys=capsys)
    assert code == 2 and "--all-app-notes" in err
    assert host.calls == []


def test_an_enrichment_style_without_enrichment_is_a_usage_error(
    tmp_path: Path, config_home: Path, host: ExportHost, capsys: pytest.CaptureFixture[str]
) -> None:
    code, _, err = _pull(
        "--all-app-notes", "--to", str(tmp_path / "o"), "--enrichment-style", "companion",
        capsys=capsys,
    )  # fmt: skip
    assert code == 2 and "--with-enrichment" in err
    assert host.calls == []


def test_a_host_with_export_off_is_refused_before_any_note_is_touched(
    tmp_path: Path, config_home: Path, api: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    host = ExportHost(api, export_on=False)
    _app_note(host)

    code, _, err = _pull("--all-app-notes", "--to", str(tmp_path / "out"), capsys=capsys)

    assert code == 1 and "export turned off" in err
    assert host.exports == []


def test_a_file_where_the_folder_should_be_is_a_usage_error(
    tmp_path: Path, config_home: Path, host: ExportHost, capsys: pytest.CaptureFixture[str]
) -> None:
    afile = write(tmp_path, "out", "not a folder")
    code, _, err = _pull("--all-app-notes", "--to", str(afile), capsys=capsys)
    assert code == 2 and "not a folder" in err


def test_paging_through_a_long_list_pulls_every_app_note(
    tmp_path: Path, config_home: Path, api: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    host = ExportHost(api, page_size=2)
    for n in range(5):
        host.add_app_note(f"Note {n}", f"body {n}\n")
    # an imported note is in the same listing and must not be pulled by --all-app-notes
    host.seed("doc", {"source_path": "x.md", "source_workspace": "W", "title": "x",
                      "content_hash": sha(b"x"), "attachments": [], "body_md": "x",
                      "source_system": "obsidian"})  # fmt: skip

    code, result, _ = _pull("--all-app-notes", "--to", str(tmp_path / "out"), capsys=capsys)

    assert code == 0
    assert [p["path"] for p in result["pulled"]] == [f"Note {n}.md" for n in range(5)]


# --- the round trip (ADR §3.7) -------------------------------------------------------------


def test_round_trip_of_an_imported_note_pull_then_scan_then_sync_changes_nothing(
    tmp_path: Path, config_home: Path, host: ExportHost, capsys: pytest.CaptureFixture[str]
) -> None:
    _, note, arp_id = _synced_vault(tmp_path, capsys, root="a")
    original = note.read_bytes()
    uploads = len(host.upserts), host.put_calls()
    # a second vault of the same name, as on another machine, with the folder to pull into
    other = make_vault(tmp_path / "b")
    folder = other / "Masterclasses"

    code, result, _ = _pull(arp_id, "--to", str(folder), capsys=capsys)
    assert code == 0 and result["pulled"][0]["path"] == "2026-10-18 Roy Howat.md"

    pulled = folder / "2026-10-18 Roy Howat.md"
    assert pulled.read_bytes() == original  # byte-equal body
    scan = _cli("scan", str(folder), capsys=capsys)
    assert [n["path"] for n in scan["unchanged"]] == ["Masterclasses/2026-10-18 Roy Howat.md"]
    assert scan["new"] == scan["changed"] == scan["renamed"] == scan["deleted"] == []

    synced = _cli("sync", str(folder), "--verify", capsys=capsys)
    (item,) = synced["synced"]
    assert item["outcome"] == "unchanged" and item["verified"] is True
    assert item["uploaded"] == []
    assert host.put_calls() == uploads[1]  # same sha256s: nothing new went over the wire
    assert pulled.read_bytes() == original  # and sync did not touch the file


def test_round_trip_of_an_app_note_syncs_with_the_same_blobs_and_then_stays_unchanged(
    tmp_path: Path, config_home: Path, host: ExportHost, capsys: pytest.CaptureFixture[str]
) -> None:
    _app_note(host)
    vault = make_vault(tmp_path)
    folder = vault / "Pulled"
    _pull("--all-app-notes", "--to", str(folder), capsys=capsys)
    pulled = (folder / "Op 10 notes.md").read_bytes()

    scan = _cli("scan", str(folder), capsys=capsys)
    assert [n["path"] for n in scan["new"]] == ["Pulled/Op 10 notes.md"]  # the host has no row yet
    assert {a["sha256"] for a in scan["new"][0]["attachments"]} == {sha(PNG_A), sha(PNG_B)}
    assert scan["new"][0]["unresolved_embeds"] == []  # every rewritten embed resolves

    first = _cli("sync", str(folder), "--verify", capsys=capsys)
    assert first["synced"][0]["outcome"] == "created" and first["synced"][0]["verified"] is True
    assert host.put_calls() == 0  # the host already held both blobs: same sha256s
    (payload,) = host.upserts
    assert payload["body_md"].encode("utf-8") == pulled
    assert sorted(a["sha256"] for a in payload["attachments"]) == sorted([sha(PNG_A), sha(PNG_B)])

    second = _cli("sync", str(folder), "--verify", capsys=capsys)
    assert second["synced"][0]["outcome"] == "unchanged" and second["synced"][0]["verified"]
    assert (folder / "Op 10 notes.md").read_bytes() == pulled
