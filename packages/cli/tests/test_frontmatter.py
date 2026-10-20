"""The D1 one-line `arp_id` insert and the Obsidian adapter rules (CLI-b, ga-mxal.36)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from arp_notes_cli.frontmatter import (
    BOM,
    FrontmatterError,
    derive_note_date,
    derive_person,
    derive_title,
    ensure_arp_id,
    guess_kind,
    parse_frontmatter,
)
from arp_notes_cli.scan import read_arp_id, split_frontmatter

NEW_ID = "11111111-2222-4333-8444-555555555555"
CORPUS = (Path(__file__).parent / "fixtures" / "obsidian-synthetic.md").read_bytes()
# The spike's 33-construct corpus already carries an arp_id; take it out to sync a fresh note.
FRESH = re.sub(rb"^arp_id: [^\n]*\n", b"", CORPUS, count=1, flags=re.MULTILINE)
assert FRESH != CORPUS and b"arp_id" not in FRESH


def _crlf(data: bytes) -> bytes:
    return data.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")


def _assert_one_line_added(original: bytes, result: bytes, line: bytes, at: int) -> None:
    """`result` is `original` with exactly `line` spliced in at byte offset `at`."""
    assert result == original[:at] + line + original[at:]


# --- the D1 byte test ----------------------------------------------------------------------


def test_corpus_with_frontmatter_gets_exactly_one_line_after_the_opening_fence() -> None:
    assert FRESH.startswith(b"---\ncreation date:")
    result, arp_id, inserted = ensure_arp_id(FRESH, NEW_ID)
    assert inserted and arp_id == NEW_ID
    _assert_one_line_added(FRESH, result, f"arp_id: {NEW_ID}\n".encode(), len(b"---\n"))
    assert read_arp_id(result.decode()) == NEW_ID


def test_every_other_byte_survives_in_crlf_and_bom_variants() -> None:
    for original in (_crlf(FRESH), BOM + FRESH, BOM + _crlf(FRESH)):
        result, _, inserted = ensure_arp_id(original, NEW_ID)
        newline = b"\r\n" if b"\r\n" in original[:12] else b"\n"
        bom = len(BOM) if original.startswith(BOM) else 0
        assert inserted
        _assert_one_line_added(
            original,
            result,
            f"arp_id: {NEW_ID}".encode() + newline,
            bom + len(b"---") + len(newline),
        )
        assert result.startswith(BOM) == original.startswith(BOM)


def test_templater_dataview_and_spaced_keys_are_not_reserialised() -> None:
    original = (
        b"---\n"
        b"creation date: 2026-10-18 09:03\n"
        b'created: <% tp.date.now("YYYY-MM-DD") %>\n'
        b"tags:   [a,   b]\n"
        b"---\n"
        b"Attendees:: [[Roy Howat]]\n"
        b"`=this.file.name`\n"
    )
    result, _, _ = ensure_arp_id(original, NEW_ID)
    assert result.replace(f"arp_id: {NEW_ID}\n".encode(), b"", 1) == original


def test_a_note_without_frontmatter_gets_a_block_in_front_and_nothing_else_changes() -> None:
    original = b"# Plain note\n\nNo frontmatter here.\n"
    result, _, inserted = ensure_arp_id(original, NEW_ID)
    assert inserted
    assert result == f"---\narp_id: {NEW_ID}\n---\n".encode() + original


def test_a_new_block_follows_the_files_line_ending_and_keeps_the_bom_first() -> None:
    original = BOM + b"# Windows note\r\nbody\r\n"
    result, _, _ = ensure_arp_id(original, NEW_ID)
    assert result == BOM + f"---\r\narp_id: {NEW_ID}\r\n---\r\n".encode() + original[len(BOM) :]


def test_an_unterminated_leading_fence_is_a_horizontal_rule_not_frontmatter() -> None:
    original = b"---\nnot frontmatter, there is no closing fence\n"
    assert split_frontmatter(original.decode())[0] is None
    result, _, _ = ensure_arp_id(original, NEW_ID)
    assert result == f"---\narp_id: {NEW_ID}\n---\n".encode() + original


def test_empty_file_gets_just_the_block() -> None:
    result, _, _ = ensure_arp_id(b"", NEW_ID)
    assert result == f"---\narp_id: {NEW_ID}\n---\n".encode()


def test_a_note_that_already_has_an_id_is_returned_untouched() -> None:
    result, arp_id, inserted = ensure_arp_id(CORPUS, NEW_ID)
    assert (result, arp_id, inserted) == (CORPUS, "3f1c2a9e-7b4d-4c1e-9f0a-1b2c3d4e5f60", False)


def test_a_quoted_existing_id_is_read_without_its_quotes() -> None:
    _, arp_id, inserted = ensure_arp_id(b'---\narp_id: "abc"\n---\nx\n', NEW_ID)
    assert (arp_id, inserted) == ("abc", False)


def test_an_empty_arp_id_key_is_refused_rather_than_duplicated() -> None:
    with pytest.raises(FrontmatterError, match="no value"):
        ensure_arp_id(b"---\narp_id:\ntitle: x\n---\nbody\n", NEW_ID)


def test_non_utf8_is_refused() -> None:
    with pytest.raises(FrontmatterError, match="UTF-8"):
        ensure_arp_id(b"---\ntitle: caf\xe9\n---\n", NEW_ID)


# --- lenient parse -------------------------------------------------------------------------


def test_parse_keeps_unknown_constructs_as_strings() -> None:
    block, _ = split_frontmatter(CORPUS.decode())
    fm = parse_frontmatter(block)
    assert fm["arp_id"] == "3f1c2a9e-7b4d-4c1e-9f0a-1b2c3d4e5f60"
    assert fm["creation date"] == "2026-10-18 09:03"
    assert fm["tags"] == ["MeetingNote", "piano/chopin"]
    assert fm["aliases"] == ["Howat masterclass"]
    assert fm["meeting-date"] == "2026-10-18"
    assert fm["cssclasses"] == "wide"


def test_parse_handles_templater_quotes_wikilinks_and_block_scalars() -> None:
    fm = parse_frontmatter(
        'created: <% tp.date.now("YYYY-MM-DD") %>\n'
        'title: "Quoted: title"\n'
        "presenter: [[Roy Howat]]\n"
        'author: "[[Jane Doe|Jane]]"\n'
        "summary: |\n"
        "  line one\n"
        "  line two\n"
        "empty:\n"
        "# a comment\n"
        "weird line without a colon\n"
        "nested:\n"
        "  inner: value\n"
    )
    assert fm["created"] == '<% tp.date.now("YYYY-MM-DD") %>'
    assert fm["title"] == "Quoted: title"
    assert fm["presenter"] == "[[Roy Howat]]"
    assert fm["author"] == "[[Jane Doe|Jane]]"
    assert fm["summary"] == "line one\nline two"
    assert fm["empty"] == ""
    assert fm["nested"] == "inner: value"


def test_parse_of_nothing_is_empty() -> None:
    assert parse_frontmatter(None) == {} and parse_frontmatter("") == {}


# --- adapter rules (A.5) -------------------------------------------------------------------


def test_title_is_frontmatter_title_else_the_filename_stem() -> None:
    assert derive_title({"title": " Real title "}, "A/b.md") == "Real title"
    assert derive_title({}, "Meetings/2026-10-18 Roy Howat.md") == "2026-10-18 Roy Howat"
    assert derive_title({"title": ""}, "x/y.md") == "y"


def test_note_date_prefers_meeting_date_then_date_then_created_then_the_filename() -> None:
    assert derive_note_date({"meeting-date": "2026-10-18", "date": "2020-01-01"}, "x.md") == (
        "2026-10-18"
    )
    assert derive_note_date({"date": "2026-03-04T10:00:00"}, "x.md") == "2026-03-04"
    assert derive_note_date({"created": "2026-03-04"}, "x.md") == "2026-03-04"
    assert derive_note_date({"date": "last Tuesday"}, "2025-12-31 Retro.md") == "2025-12-31"
    assert derive_note_date({"date": "2026-13-45"}, "plain.md") is None
    assert derive_note_date({}, "Folder/2026-10-18 Masterclass.md") == "2026-10-18"
    assert derive_note_date({}, "plain.md") is None


def test_person_is_the_first_wikilink_in_attendees_presenter_or_author() -> None:
    body = "**Attendees**:: [[Roy Howat]], [[Someone Else]]\nduration:: 25\n"
    assert derive_person({}, body) == "Roy Howat"
    assert derive_person({"presenter": "[[Jane Doe|Jane]]"}, body) == "Jane Doe"
    assert derive_person({"author": ["[[A B]]"]}, "") == "A B"
    assert derive_person({}, "attendees:: [[Low Case]]") == "Low Case"
    assert derive_person({}, "Attendees:: nobody linked") is None
    assert derive_person({}, "```\nAttendees:: [[In Code]]\n```\n") is None
    assert derive_person({}, "Mentions [[Roy Howat]] in prose only") is None


def test_kind_heuristics_follow_d8() -> None:
    assert guess_kind({"tags": ["MeetingNote"]}, "x.md") == "meeting"
    assert guess_kind({"tags": "MeetingNote, piano"}, "x.md") == "meeting"
    assert guess_kind({}, "2026-10-18 Roy Howat masterclass.md") == "masterclass"
    assert guess_kind({"title": "Spring Workshop"}, "x.md") == "workshop"
    assert guess_kind({"tags": ["#lecture/music"]}, "x.md") == "lecture"
    # a kind named in the title is more specific than the generic MeetingNote tag
    assert guess_kind({"tags": ["MeetingNote"]}, "Howat masterclass.md") == "masterclass"
    assert guess_kind({}, "plain.md") is None
