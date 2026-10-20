"""`arp-notes init --host fastapi` yields a host that reaches green conformance (C9, ga-mxal.23).

The scaffold's two TODO ports that only the host can write, the database and the sign-in, are
filled with the test doubles; everything init generated (storage, signer, the abstaining link
scheme, the router mount, the MCP endpoint, the drift test and the conformance test) runs as is.
"""

from __future__ import annotations

import importlib
import importlib.util
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from arp_notes.testing.fakedb import FakeDb
from arp_notes_cli.main import main
from arp_notes_conformance import suite
from fastapi import FastAPI, HTTPException, Request
from ref_host import TOKEN, USER

PACKAGE = "scaffolded_host"


class TestPrincipal:
    __test__ = False  # not a pytest class

    def current_user_id(self, request: Request) -> str:
        scheme, _, token = request.headers.get("authorization", "").partition(" ")
        if scheme.lower() != "bearer" or token != TOKEN:
            raise HTTPException(status_code=401, detail="missing or unknown token")
        return USER


@pytest.fixture
def scaffold(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, notes_db: FakeDb) -> tuple[Any, Any]:
    """init into an empty project, then import what it wrote with the two host ports filled in."""
    code = main(["init", "--host", "fastapi", "--dir", str(tmp_path), "--package", PACKAGE])
    assert code == 0
    monkeypatch.syspath_prepend(str(tmp_path))
    importlib.invalidate_caches()
    adapter = importlib.import_module(f"{PACKAGE}.arp_notes_host")
    monkeypatch.setattr(adapter, "HostDb", lambda: notes_db)
    monkeypatch.setattr(adapter, "HostPrincipal", TestPrincipal)

    path = tmp_path / "tests" / "test_arp_notes_conformance.py"
    spec = importlib.util.spec_from_file_location("scaffolded_conformance_test", path)
    assert spec is not None and spec.loader is not None
    test_module: ModuleType = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(test_module)
    monkeypatch.setattr(test_module, "TOKEN", TOKEN)
    monkeypatch.delitem(sys.modules, f"{PACKAGE}.arp_notes_host", raising=False)
    monkeypatch.delitem(sys.modules, PACKAGE, raising=False)
    return adapter, test_module


def test_the_generated_tests_pass(
    scaffold: tuple[Any, Any], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _, tests = scaffold
    tests.test_migrations_match_arp_notes_core()
    tests.test_conformance(monkeypatch, tmp_path)


def test_everything_the_host_did_not_write_runs(
    scaffold: tuple[Any, Any], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Only the link checks wait for the host: its scheme abstains, the fixture names no entity."""
    adapter, tests = scaffold
    monkeypatch.setenv("ARP_NOTES_SIGNER_SECRET", "secret")
    monkeypatch.setenv("ARP_NOTES_BLOB_DIR", str(tmp_path / "blobs"))
    app = FastAPI()
    cfg = adapter.mount_notes(app)
    adapter.mount_notes_mcp_http(app, cfg)

    report = suite(app=app, token=TOKEN, fixture=tests.FIXTURE, raise_on_failure=False)
    print("\n".join(report.lines()))
    assert report.ok
    skipped = {o.name: o.detail for o in report.of("skipped")}
    assert not [name for name in skipped if name.startswith("mcp.")]
    assert not [name for name in skipped if name.startswith("attachments.") and "upload" in name]
    waiting = [name for name, why in skipped.items() if "link_target" in why or "recognised" in why]
    assert waiting, "the link checks say what they are waiting for"
    assert len(report.of("passed")) > 30


def test_the_drift_test_catches_a_stale_copy(scaffold: tuple[Any, Any], tmp_path: Path) -> None:
    _, tests = scaffold
    copy = tmp_path / "migrations" / "arp_notes_001_notes.sql"
    copy.write_text(copy.read_text(encoding="utf-8") + "\n-- edited\n", encoding="utf-8")
    with pytest.raises(AssertionError, match="drifted from arp-notes-core"):
        tests.test_migrations_match_arp_notes_core()


def test_the_generated_files_are_lint_clean(tmp_path: Path) -> None:
    assert main(["init", "--host", "fastapi", "--dir", str(tmp_path)]) == 0
    result = subprocess.run(
        [
            sys.executable, "-m", "ruff", "check", "--isolated", "--line-length", "100",
            "--select", "E,F,B,UP", str(tmp_path / "app"), str(tmp_path / "tests"),
        ],
        capture_output=True,
        text=True,
    )  # fmt: skip
    assert result.returncode == 0, result.stdout + result.stderr
