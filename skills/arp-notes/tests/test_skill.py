"""The arp-notes skill must agree with the code it drives (ga-mxal.7).

The skill is prose, so nothing else would notice if a CLI flag, an MCP tool or a proposal field it
names were renamed. These tests read the skill's files and check every such reference against the
real CLI parser, the real MCP tool list and the real pydantic models.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import stat
import subprocess
from pathlib import Path
from typing import get_args

import pytest
from arp_notes import mcp, models
from arp_notes_cli.main import build_parser
from pydantic import BaseModel

SKILL_DIR = Path(__file__).resolve().parents[1]
REPO = SKILL_DIR.parents[1]
SKILL_MD = SKILL_DIR / "SKILL.md"
DOCS = [SKILL_MD, SKILL_DIR / "README.md", *sorted((SKILL_DIR / "references").glob("*.md"))]
WRAPPER = SKILL_DIR / "scripts" / "arp-notes"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _frontmatter(text: str) -> dict[str, str]:
    """Top-level keys of the SKILL.md frontmatter. Folded (`>-`) values are joined with spaces."""
    lines = text.split("\n")
    assert lines[0] == "---"
    end = lines.index("---", 1)
    out: dict[str, str] = {}
    key = ""
    for line in lines[1:end]:
        top = re.match(r"^([A-Za-z_-]+):\s*(.*)$", line)
        if top and not line.startswith(" "):
            key, value = top.group(1), top.group(2).strip()
            out[key] = "" if value in (">-", ">", "|", "|-") else value
        elif key and line.strip():
            out[key] = (out[key] + " " + line.strip()).strip()
    return out


# --- Agent Skills frontmatter -----------------------------------------------------------------


def test_frontmatter_meets_the_agent_skills_rules() -> None:
    meta = _frontmatter(_text(SKILL_MD))
    assert meta["name"] == SKILL_DIR.name == "arp-notes"
    assert re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", meta["name"]) and len(meta["name"]) <= 64
    assert "claude" not in meta["name"] and "anthropic" not in meta["name"]
    assert 0 < len(meta["description"]) <= 1024
    assert len(meta["compatibility"]) <= 500


def test_description_carries_the_triggers() -> None:
    description = _frontmatter(_text(SKILL_MD))["description"].lower()
    for trigger in ("sync my notes", "masterclass", "folder"):
        assert trigger in description


def test_skill_body_stays_short_enough_to_load() -> None:
    assert len(_text(SKILL_MD).splitlines()) < 500


def test_every_relative_link_resolves() -> None:
    for doc in DOCS:
        for target in re.findall(r"\]\((?!https?:|#)([^)#]+)(?:#[^)]*)?\)", _text(doc)):
            assert (doc.parent / target).resolve().exists(), f"{doc.name} links to {target}"


# --- CLI commands and flags it names -----------------------------------------------------------


def _subcommands() -> dict[str, set[str]]:
    parser = build_parser()
    (group,) = [a for a in parser._actions if isinstance(a, argparse._SubParsersAction)]
    return {
        name: {opt for action in sub._actions for opt in action.option_strings}
        for name, sub in group.choices.items()
    }


_CLI_CALL = re.compile(r"(?:scripts/|\$ )?arp-notes ([a-z]+)\b([^`\n]*)")


def _cli_calls(text: str) -> list[tuple[str, str]]:
    """(subcommand, rest of the line) for each code span or fenced line that runs the CLI."""
    calls = []
    for span in re.findall(r"`([^`\n]+)`", text) + re.findall(r"^\$ (arp-notes .*)$", text, re.M):
        match = _CLI_CALL.match(span.strip())
        if match and (span.startswith(("scripts/arp-notes", "arp-notes", "$ arp-notes"))):
            calls.append((match.group(1), match.group(2)))
    return calls


def test_cli_commands_and_flags_it_names_exist() -> None:
    commands = _subcommands()
    seen: set[str] = set()
    for doc in DOCS:
        for command, rest in _cli_calls(_text(doc)):
            assert command in commands, f"{doc.name}: no such command arp-notes {command}"
            seen.add(command)
            for flag in re.findall(r"(?<![\w-])(--[a-z][a-z-]*)", rest):
                assert flag in commands[command], f"{doc.name}: arp-notes {command} has no {flag}"
    # the flow needs these; losing one from the prose would silently break a step
    assert {"capabilities", "scan", "sync", "tombstone", "login"} <= seen


def test_skill_asks_for_json_and_dry_run_where_the_flow_needs_them() -> None:
    body = _text(SKILL_MD)
    needles = ("scan <paths", "sync <paths", "--dry-run", "--no-write-id", "--verify", "--kind")
    for needle in needles:
        assert needle in body


# --- MCP tools and the fields it reads ---------------------------------------------------------


def _tool_names() -> set[str]:
    return {tool.name for tool in mcp.TOOLS}


def _model_fields() -> set[str]:
    fields: set[str] = set()
    for obj in vars(models).values():
        if isinstance(obj, type) and issubclass(obj, BaseModel):
            fields |= set(obj.model_fields)
    return fields


# Words in backticks that are neither tools nor model fields: enum values, CLI JSON keys, literals.
_NOT_TOOLS = {
    "arp_id",
    "confirm_token",
    "dry_run",
    "dry_run_first",
    "plan_changed",
    "unresolved_embeds",
    "would_create",
    "would_upload",
    "would_write_id",
    "note_id",
    "source_systems",
    "mime_allowlist",
    "max_attachment_bytes",
    "limits",
    "kind_hint",
    "composer_label",
    "fix_index",
    "issue_key",
    "entity_label",
    "entity_type",
    "entity_id",
    "llm_enrich",
    "propose_on_sync",
    "duplicate_group",
    "mention_count",
    "link_index",
    "expires_at",
    "review_pending",
    "links_created",
    "links_rejected",
    "backlog_created",
    "takeaways_created",
    "someday_created",
    "proposed_at",
    "generated_by",
    "action_items",
    "source_doc_id",
    "source_system",
    "no_write_id",
    "renamed_from",
}


def test_every_snake_case_word_is_a_tool_a_model_field_or_a_known_literal() -> None:
    known = _tool_names() | _model_fields() | _NOT_TOOLS | set(get_args(models.HygieneKind))
    for doc in DOCS:
        for word in set(re.findall(r"`([a-z]+(?:_[a-z]+)+)\b", _text(doc))):
            assert word in known, f"{doc.name} mentions `{word}`, which is not in the code"


def test_the_tools_the_flow_calls_are_registered_and_named() -> None:
    corpus = "\n".join(_text(doc) for doc in DOCS)
    for name in (
        "notes_capabilities",
        "propose_note_enrichment",
        "confirm_note_enrichment",
        "get_note",
        "apply_fix",
        "merge_entities",
        "resolve_tombstone",
        "dismiss_issue",
    ):
        assert name in _tool_names(), f"{name} is no longer a notes tool"
        assert name in corpus, f"the skill never mentions {name}"


def test_propose_arguments_it_uses_are_accepted() -> None:
    schema = next(t for t in mcp.TOOLS if t.name == "propose_note_enrichment").input_schema
    assert {"note_id", "llm", "refresh"} <= set(schema["properties"])


def test_confirm_body_keys_it_documents_match_the_models() -> None:
    schema = next(t for t in mcp.TOOLS if t.name == "confirm_note_enrichment").input_schema
    assert {"note_id", "links", "rejected", "action_items", "takeaways", "deferred", "someday"} <= (
        set(schema["properties"])
    )
    review = _text(SKILL_DIR / "references" / "review.md")
    documented = {
        models.ConfirmLink: {"entity_type", "entity_id", "anchor", "quote", "proposed_by"},
        models.RejectedLink: {"entity_type", "entity_id", "anchor"},
        models.DeferredMention: {"mention", "anchor"},
        models.ConfirmAction: {"text", "anchor", "entity_type", "entity_id", "lane", "link_index"},
        models.ConfirmTakeaway: {"anchor", "comment"},
        models.SomedayMention: {"mention", "kind_hint", "composer_label", "anchor", "quote"},
    }
    for model, keys in documented.items():
        assert keys <= set(model.model_fields), f"{model.__name__} lost a documented key"
        assert all(key in review for key in keys)


def test_confidence_bands_match_the_contract() -> None:
    # K§4: high >= 0.8, medium 0.5-0.8, low < 0.5; high and medium are pre-ticked.
    review = _text(SKILL_DIR / "references" / "review.md")
    assert "≥ 0.8" in review and "0.5 – 0.8" in review and "< 0.5" in review


def test_hygiene_fix_tools_the_detectors_emit_are_covered() -> None:
    from arp_notes.hygiene import detect

    emitted = set(re.findall(r'tool="([a-z_]+)"', _text(Path(detect.__file__))))
    hygiene_doc = _text(SKILL_DIR / "references" / "hygiene.md") + _text(SKILL_MD)
    for tool in emitted:
        assert tool in hygiene_doc, f"core hygiene can emit {tool}; the skill never mentions it"


def test_capability_fields_it_reads_exist() -> None:
    fields = set(models.Capabilities.model_fields)
    body = _text(SKILL_MD)
    read = ("protocol", "source_systems", "attachments", "mime_allowlist", "kinds", "someday")
    for field in read:
        assert field in fields and field in body
    assert "max_attachment_bytes" in models.CapabilityLimits.model_fields


# --- the walkthrough is true to the fixture ----------------------------------------------------


def test_readme_walkthrough_scan_matches_the_fixture_bytes() -> None:
    fixture = REPO / "packages" / "core" / "tests" / "fixtures" / "enrich" / "masterclass.md"
    data = fixture.read_bytes()
    readme = _text(SKILL_DIR / "README.md")
    assert hashlib.sha256(data).hexdigest() in readme
    assert f'"size_bytes": {len(data)}' in readme


# --- scripts/arp-notes ------------------------------------------------------------------------


def _stub(directory: Path, name: str) -> None:
    path = directory / name
    path.write_text('#!/bin/sh\necho "$0-ran:$*"\n', encoding="utf-8")
    path.chmod(0o755)


def _run_wrapper(path_dir: Path, *args: str, **env: str) -> subprocess.CompletedProcess[str]:
    base = {"PATH": str(path_dir), "HOME": str(path_dir)}
    return subprocess.run(
        ["/bin/sh", str(WRAPPER), *args],
        env={**base, **env},
        capture_output=True,
        text=True,
        check=False,
    )


def test_wrapper_is_executable() -> None:
    assert WRAPPER.stat().st_mode & stat.S_IXUSR


def test_wrapper_prefers_an_installed_cli(tmp_path: Path) -> None:
    _stub(tmp_path, "arp-notes")
    _stub(tmp_path, "uvx")
    result = _run_wrapper(tmp_path, "scan", "x.md", "--json")
    assert result.returncode == 0
    assert result.stdout.strip() == f"{tmp_path}/arp-notes-ran:scan x.md --json"


def test_wrapper_falls_back_to_uvx_at_the_pinned_tag(tmp_path: Path) -> None:
    _stub(tmp_path, "uvx")
    result = _run_wrapper(tmp_path, "status", "--app", "pt")
    assert result.returncode == 0
    assert result.stdout.strip() == (
        f"{tmp_path}/uvx-ran:--from arp-notes @ "
        "git+https://github.com/dneigler/arp-notes@v0.1.0#subdirectory=packages/cli "
        "arp-notes status --app pt"
    )


def test_wrapper_ref_and_repo_can_be_overridden(tmp_path: Path) -> None:
    _stub(tmp_path, "uvx")
    result = _run_wrapper(
        tmp_path, "scan", ARP_NOTES_REF="main", ARP_NOTES_REPO="https://example.test/fork"
    )
    assert "git+https://example.test/fork@main#subdirectory=packages/cli" in result.stdout


def test_wrapper_says_what_to_install_when_nothing_is_there(tmp_path: Path) -> None:
    result = _run_wrapper(tmp_path, "scan")
    assert result.returncode == 127
    assert "uv" in result.stderr and "PATH" in result.stderr


@pytest.mark.skipif(os.name == "nt", reason="POSIX shell wrapper")
def test_wrapper_is_posix_sh() -> None:
    assert _text(WRAPPER).startswith("#!/usr/bin/env sh\n")
    check = subprocess.run(["/bin/sh", "-n", str(WRAPPER)], capture_output=True, check=False)
    assert check.returncode == 0
