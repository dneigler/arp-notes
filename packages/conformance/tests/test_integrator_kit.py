"""The integrator kit's documents say true things (C9, ga-mxal.23).

INTEGRATING.md and llms.txt are what a fresh LLM reads, so a stale line costs it a session. These
tests run the snippets that can run, check every name the page uses against the code, and check
the file list llms.txt hands out.
"""

from __future__ import annotations

import argparse
import ast
import dataclasses
import importlib
import re
from pathlib import Path
from typing import Any

import pytest
from arp_notes import ports
from arp_notes.config import HostConfig
from arp_notes.ports import Db, Hooks, LinkSchemes, Policy, SchemeChildren, SchemeDedupe
from arp_notes.testing.fakedb import FakeDb
from arp_notes_cli.init import register

ROOT = Path(__file__).resolve().parents[3]
INTEGRATING = (ROOT / "INTEGRATING.md").read_text(encoding="utf-8")
LLMS = (ROOT / "llms.txt").read_text(encoding="utf-8")
TEMPLATES = ROOT / "packages" / "cli" / "arp_notes_cli" / "templates"


def blocks(language: str) -> list[str]:
    return re.findall(rf"```{language}\n(.*?)```", INTEGRATING, re.S)


def block_with(language: str, needle: str) -> str:
    found = [b for b in blocks(language) if needle in b]
    assert len(found) == 1, f"expected one {language} block with {needle!r}, found {len(found)}"
    return found[0]


def run_block(source: str, **names: Any) -> dict[str, Any]:
    namespace: dict[str, Any] = dict(names)
    exec(compile(source, "INTEGRATING.md", "exec"), namespace)  # noqa: S102
    return namespace


# -- INTEGRATING.md ---------------------------------------------------------------------------


def test_every_python_block_parses() -> None:
    assert len(blocks("python")) >= 12
    for source in blocks("python"):
        ast.parse(source)


def test_every_import_the_page_shows_resolves() -> None:
    imports = 0
    for source in blocks("python"):
        for node in ast.walk(ast.parse(source)):
            if (
                isinstance(node, ast.ImportFrom)
                and node.module
                and node.module.startswith("arp_notes")
            ):
                module = importlib.import_module(node.module)
                for alias in node.names:
                    assert hasattr(module, alias.name), f"{node.module} has no {alias.name}"
                    imports += 1
    assert imports >= 15


def test_every_host_config_field_has_its_own_worked_example() -> None:
    for field in dataclasses.fields(HostConfig):
        assert f"**{field.name}**" in INTEGRATING, f"no worked example for HostConfig.{field.name}"


def test_every_policy_field_is_mentioned() -> None:
    for field in dataclasses.fields(Policy):
        assert field.name in INTEGRATING, f"Policy.{field.name} is not on the page"


def test_every_port_method_is_mentioned() -> None:
    members = {
        "Storage": ("put", "open", "delete"),
        "LinkSchemes": ("resolve", "search", "reconcile", "prefix", "entity_types"),
        "SchemeChildren": ("children",),
        "SchemeDedupe": ("dedupe_key",),
        "Hygiene": ("detect",),
        "HygieneMerge": ("merge",),
        "Principal": ("current_user_id",),
        "Signer": ("secret", "ttl_s"),
        "Db": ("run", "transaction"),
    }
    for protocol, names in members.items():
        real = set(getattr(ports, protocol).__protocol_attrs__)
        assert set(names) <= real, f"{protocol} no longer has {set(names) - real}"
        for name in names:
            assert name in INTEGRATING, f"{protocol}.{name} is not on the page"
    for hook in dataclasses.fields(Hooks):
        if hook.name != "extra":
            assert hook.name in INTEGRATING, f"Hooks.{hook.name} is not on the page"


def test_the_ui_is_installed_from_the_release_tarball() -> None:
    lines = re.findall(r"npm install (\S+)", INTEGRATING)
    assert len(lines) == 1
    assert re.fullmatch(
        r"https://github\.com/dneigler/arp-notes/releases/download/"
        r"(v\d+\.\d+\.\d+(?:-rc\.\d+)?)/arpinator-notes-ui-\d+\.\d+\.\d+(?:-rc\.\d+)?\.tgz",
        lines[0],
    )
    for text in (INTEGRATING, LLMS, *(p.read_text("utf-8") for p in TEMPLATES.rglob("*.tmpl"))):
        assert "github:dneigler" not in text and "path:packages/ui" not in text


def test_the_init_flags_the_page_names_exist() -> None:
    subparsers = argparse.ArgumentParser().add_subparsers()
    register(subparsers)
    known = {s for action in subparsers.choices["init"]._actions for s in action.option_strings}  # noqa: SLF001
    section = INTEGRATING.split("## 2 · Scaffold")[1].split("## 3 ·")[0]
    named = set(re.findall(r"`?(--[a-z-]+)", section))
    assert {"--package", "--migration-number", "--only", "--force", "--dry-run"} <= named
    assert named <= known, f"the page names flags init does not have: {named - known}"


def test_the_conformance_commands_exist() -> None:
    from arp_notes_conformance.cli import build_parser as kit_parser

    known = {s for a in kit_parser()._actions for s in a.option_strings}  # noqa: SLF001
    for flag in re.findall(r"arp-notes-conformance[^\n]*?(--[a-z-]+)", INTEGRATING):
        assert flag in known, flag


def test_the_db_snippet_is_a_working_db(arpn_pg: Any) -> None:
    info = arpn_pg.info
    dsn = f"host={info.host} port={info.port} dbname={info.dbname} user={info.user}"
    host_db = run_block(block_with("python", "class HostDb")).get("HostDb")
    assert host_db is not None
    db = host_db(dsn)
    assert isinstance(db, Db)
    db.run("CREATE TABLE doc_check (a int)")
    assert db.run("INSERT INTO doc_check VALUES (%s) RETURNING a", [1]) == [{"a": 1}]
    with pytest.raises(RuntimeError), db.transaction():
        db.run("INSERT INTO doc_check VALUES (%s)", [2])
        raise RuntimeError("roll back")
    with db.transaction():
        db.run("INSERT INTO doc_check VALUES (%s)", [3])
        with pytest.raises(RuntimeError), db.transaction():  # a savepoint
            db.run("INSERT INTO doc_check VALUES (%s)", [4])
            raise RuntimeError("roll back the inner block only")
    assert db.run("SELECT a FROM doc_check ORDER BY a") == [{"a": 1}, {"a": 3}]


def test_the_link_scheme_snippet_satisfies_the_port() -> None:
    scheme = run_block(block_with("python", "class VenueLinks"))["VenueLinks"]()
    assert isinstance(scheme, LinkSchemes)
    assert isinstance(scheme, SchemeChildren) and isinstance(scheme, SchemeDedupe)


def test_the_policy_and_judge_snippets_run() -> None:
    policy = run_block(block_with("python", "policy = Policy("))["policy"]
    assert policy.propose_on_sync == "search" and policy.export is True
    ns = run_block(
        block_with("python", "ChainJudge("),
        JEV_API_KEY="k",
        call_my_llm=lambda prompt: "{}",
    )
    assert ns["judge"].name == "jev-choice>haiku"


def test_the_hygiene_snippet_returns_valid_issues() -> None:
    hygiene = run_block(block_with("python", "class HostHygiene"))["HostHygiene"]()
    issues = hygiene.detect("u1", "all")
    assert issues[0].kind == "duplicate_entities" and len(issues[0].subjects) == 2


def test_the_assembled_config_snippet_builds_a_host_config(fakedb: FakeDb) -> None:
    source = block_with("python", "def build_host_config")
    tree = ast.parse(source)
    assert any(isinstance(n, ast.FunctionDef) and n.name == "build_host_config" for n in tree.body)
    call = next(
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "HostConfig"
    )
    assert {k.arg for k in call.keywords} <= {f.name for f in dataclasses.fields(HostConfig)}


# -- llms.txt ---------------------------------------------------------------------------------


def test_llms_txt_follows_the_format() -> None:
    lines = LLMS.splitlines()
    assert lines[0] == "# arp-notes"
    assert lines[2].startswith("> ")
    assert all(h in LLMS for h in ("## Integrate", "## Contract", "## Optional"))


def test_llms_txt_points_agents_at_the_right_files() -> None:
    assert "INTEGRATING.md" in LLMS.split("##")[0]  # read first, before any list
    for needle in ("INTEGRATING.md", "PROTOCOL.md", "schemas", "examples/fastapi-minimal"):
        assert needle in LLMS


def test_every_link_in_llms_txt_is_a_file_in_this_repo() -> None:
    prefixes = (
        "https://raw.githubusercontent.com/dneigler/arp-notes/main/",
        "https://github.com/dneigler/arp-notes/tree/main/",
    )
    links = re.findall(r"\]\((https?://[^)]+)\)", LLMS)
    assert len(links) >= 10
    for url in links:
        prefix = next((p for p in prefixes if url.startswith(p)), None)
        assert prefix, f"{url} is not a link into this repository's main branch"
        assert (ROOT / url.removeprefix(prefix)).exists(), f"{url}: no such path"
