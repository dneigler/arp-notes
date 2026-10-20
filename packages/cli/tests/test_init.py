"""`arp-notes init --host fastapi` (C9, ga-mxal.23): what it writes, where, and what it refuses."""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest
from arp_notes.schema import ddl, migrations
from arp_notes_cli.init import (
    detect_package,
    migration_names,
    module_name,
    ui_install_line,
)
from arp_notes_cli.main import main

SHIPPED = {"001_notes.sql": ddl(), **dict(migrations())}


def init(root: Path, *args: str) -> int:
    return main(["init", "--host", "fastapi", "--dir", str(root), *args])


def parses(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def test_fresh_app_gets_the_adapter_the_migrations_and_the_test(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert init(tmp_path) == 0
    out = capsys.readouterr().out

    adapter = tmp_path / "app" / "arp_notes_host.py"
    text = adapter.read_text(encoding="utf-8")
    parses(adapter)
    assert (tmp_path / "app" / "__init__.py").is_file()  # created with the package
    assert text.count("TODO(arp-notes)") >= 6
    for name in ("HostDb", "HostPrincipal", "HostSigner", "HostLinks"):
        assert f"class {name}" in text
    for fn in ("build_host_config", "mount_notes", "register_notes_mcp", "mount_notes_mcp_http"):
        assert f"def {fn}(" in text
    assert "@@" not in text

    for core_name, sql in SHIPPED.items():  # byte-equal copies, DDL and every later delta
        assert (tmp_path / "migrations" / f"arp_notes_{core_name}").read_text("utf-8") == sql

    test = tmp_path / "tests" / "test_arp_notes_conformance.py"
    parses(test)
    body = test.read_text(encoding="utf-8")
    assert "from app.arp_notes_host import mount_notes, mount_notes_mcp_http" in body
    assert "@@" not in body

    assert "Next:" in out
    assert "mount_notes(app)" in out
    assert "from app.arp_notes_host import mount_notes" in out
    assert "mount_notes does not serve MCP" in out and "ARP_NOTES_MCP_URL" in out


def test_next_steps_name_the_ui_tarball_not_a_git_subdirectory(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    init(tmp_path)
    out = capsys.readouterr().out
    assert "https://github.com/dneigler/arp-notes/releases/download/" in out
    assert ".tgz" in out
    assert "github:dneigler" not in out and "path:packages/ui" not in out


@pytest.mark.parametrize(
    ("version", "line"),
    [
        (
            "0.1.0rc1",
            "npm install https://github.com/dneigler/arp-notes/releases/download/"
            "v0.1.0-rc.1/arpinator-notes-ui-0.1.0-rc.1.tgz",
        ),
        (
            "0.1.0",
            "npm install https://github.com/dneigler/arp-notes/releases/download/"
            "v0.1.0/arpinator-notes-ui-0.1.0.tgz",
        ),
        (
            "unknown version",
            "npm install https://github.com/dneigler/arp-notes/releases/download/"
            "<tag>/arpinator-notes-ui-<version>.tgz",
        ),
    ],
)
def test_ui_install_line_is_the_release_tarball(version: str, line: str) -> None:
    assert ui_install_line(version) == line


def test_the_copied_migrations_are_what_the_drift_test_expects(tmp_path: Path) -> None:
    init(tmp_path)
    test = (tmp_path / "tests" / "test_arp_notes_conformance.py").read_text(encoding="utf-8")
    for core_name in SHIPPED:
        assert f'"{core_name}": "arp_notes_{core_name}"' in test
    assert 'Path(__file__).resolve().parent / "../migrations"' in test


def test_a_second_run_changes_nothing(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    init(tmp_path)
    before = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    capsys.readouterr()
    assert init(tmp_path) == 0
    out = capsys.readouterr().out
    assert out.count("unchanged") == 4
    assert {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()} == before


def test_a_file_you_edited_is_left_alone_until_force(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    init(tmp_path)
    adapter = tmp_path / "app" / "arp_notes_host.py"
    adapter.write_text("# my adapter\n", encoding="utf-8")
    capsys.readouterr()

    assert init(tmp_path) == 1
    captured = capsys.readouterr()
    assert "exists (differs)" in captured.out and "app/arp_notes_host.py" in captured.out
    assert "--force" in captured.err
    assert adapter.read_text(encoding="utf-8") == "# my adapter\n"

    assert init(tmp_path, "--force") == 0
    assert "TODO(arp-notes)" in adapter.read_text(encoding="utf-8")


def test_dry_run_writes_nothing(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert init(tmp_path, "--dry-run") == 0
    assert list(tmp_path.iterdir()) == []
    assert capsys.readouterr().out.count("would create") == 2 + len(SHIPPED)


def test_only_migrations_is_the_upgrade_path(tmp_path: Path) -> None:
    init(tmp_path)
    (tmp_path / "migrations" / "arp_notes_002_note_links_lane.sql").unlink()  # an older pin
    adapter = tmp_path / "app" / "arp_notes_host.py"
    adapter.write_text("# edited\n", encoding="utf-8")

    assert init(tmp_path, "--only", "migrations") == 0
    assert (tmp_path / "migrations" / "arp_notes_002_note_links_lane.sql").is_file()
    assert adapter.read_text(encoding="utf-8") == "# edited\n"


def test_only_tests_leaves_the_rest_out(tmp_path: Path) -> None:
    assert init(tmp_path, "--only", "tests") == 0
    assert sorted(p.name for p in tmp_path.rglob("*") if p.is_file()) == [
        "test_arp_notes_conformance.py"
    ]


def test_the_hosts_own_migration_numbers(tmp_path: Path) -> None:
    assert init(tmp_path, "--migration-number", "43") == 0
    names = sorted(p.name for p in (tmp_path / "migrations").iterdir())
    assert names == ["043_notes.sql", "044_note_links_lane.sql"]
    test = (tmp_path / "tests" / "test_arp_notes_conformance.py").read_text(encoding="utf-8")
    assert '"001_notes.sql": "043_notes.sql"' in test
    assert '"002_note_links_lane.sql": "044_note_links_lane.sql"' in test


def test_it_finds_the_folders_the_app_already_has(tmp_path: Path) -> None:
    (tmp_path / "src" / "shop").mkdir(parents=True)
    (tmp_path / "src" / "shop" / "__init__.py").write_text("")
    (tmp_path / "db" / "migrations").mkdir(parents=True)
    (tmp_path / "backend" / "tests").mkdir(parents=True)

    assert init(tmp_path) == 0
    assert (tmp_path / "src" / "shop" / "arp_notes_host.py").is_file()
    assert (tmp_path / "db" / "migrations" / "arp_notes_001_notes.sql").is_file()
    test = tmp_path / "backend" / "tests" / "test_arp_notes_conformance.py"
    assert "from shop.arp_notes_host import" in test.read_text(encoding="utf-8")
    assert '"../../db/migrations"' in test.read_text(encoding="utf-8")


def test_explicit_folders_and_module_win(tmp_path: Path) -> None:
    assert (
        init(
            tmp_path,
            "--package", "svc/api",
            "--module", "svc.api",
            "--migrations-dir", "sql",
            "--tests-dir", "checks",
        )
        == 0
    )  # fmt: skip
    assert (tmp_path / "svc" / "api" / "arp_notes_host.py").is_file()
    assert (tmp_path / "sql" / "arp_notes_001_notes.sql").is_file()
    test = (tmp_path / "checks" / "test_arp_notes_conformance.py").read_text(encoding="utf-8")
    assert "from svc.api.arp_notes_host import" in test


def test_an_existing_package_without_init_py_is_left_alone(tmp_path: Path) -> None:
    (tmp_path / "app").mkdir()
    assert init(tmp_path) == 0
    assert not (tmp_path / "app" / "__init__.py").exists()


@pytest.mark.parametrize(
    ("package", "module"),
    [("app", "app"), ("src/shop", "shop"), ("backend/app", "app"), ("svc/api", "svc.api")],
)
def test_module_name(package: str, module: str) -> None:
    assert module_name(package) == module


def test_detect_package_prefers_app_then_the_single_src_package(tmp_path: Path) -> None:
    assert detect_package(tmp_path) == "app"  # nothing there: app/ is created
    (tmp_path / "src" / "one").mkdir(parents=True)
    (tmp_path / "src" / "one" / "__init__.py").write_text("")
    assert detect_package(tmp_path) == "src/one"
    (tmp_path / "src" / "two").mkdir()
    (tmp_path / "src" / "two" / "__init__.py").write_text("")
    assert detect_package(tmp_path) == "app"  # two candidates: not guessing
    (tmp_path / "app").mkdir()
    assert detect_package(tmp_path) == "app"


def test_migration_names() -> None:
    files = [("001_notes.sql", ""), ("002_note_links_lane.sql", "")]
    assert migration_names(files, None) == {
        "001_notes.sql": "arp_notes_001_notes.sql",
        "002_note_links_lane.sql": "arp_notes_002_note_links_lane.sql",
    }
    assert migration_names(files, 7) == {
        "001_notes.sql": "007_notes.sql",
        "002_note_links_lane.sql": "008_note_links_lane.sql",
    }


def test_core_not_installed_says_how_to_install_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setitem(sys.modules, "arp_notes.schema", None)  # `import` now raises ImportError
    assert init(tmp_path) == 2
    err = capsys.readouterr().err
    assert "arp-notes-core" in err and "uv add" in err
    assert list(tmp_path.iterdir()) == []


def test_a_missing_dir_is_bad_input(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert init(tmp_path / "nope") == 2
    assert "not a directory" in capsys.readouterr().err


def test_host_is_required_and_checked() -> None:
    with pytest.raises(SystemExit) as exc:
        main(["init"])
    assert exc.value.code == 2
    with pytest.raises(SystemExit) as exc:
        main(["init", "--host", "flask"])
    assert exc.value.code == 2
