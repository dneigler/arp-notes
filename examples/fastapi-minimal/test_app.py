"""The example host passes the conformance kit, in process and over HTTP (C7a + C7b), and its
copied migrations have not drifted from `arp_notes.schema` (ADR §9.4)."""

from __future__ import annotations

import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import uvicorn
from app import HERE, PsycopgDb, build_host_config, make_app, migrate
from arp_notes.schema import ddl, migrations
from arp_notes.testing.fakedb import FakeDb
from arp_notes_conformance import suite
from fastapi import FastAPI

TOKEN = "example-token"
EXPECTED_SKIPS = {
    "attachments.mime_allowlist",  # the policy accepts any MIME type
    "attachments.refused_when_off",  # the policy takes attachments
    "export.disabled_is_refused",  # the policy allows export
    "hygiene.merge_entities_dry_run",  # no Hygiene.merge: a host that cannot merge says 501
}


@pytest.fixture
def host(notes_db: FakeDb, tmp_path: Path) -> FastAPI:
    return make_app(build_host_config(notes_db, tmp_path / "blobs", {TOKEN: "example-user"}))


def test_migrations_match_arp_notes_core() -> None:
    core = {"001_notes.sql": ddl(), **dict(migrations())}
    copies = {p.name.removeprefix("arp_notes_"): p for p in (HERE / "migrations").glob("*.sql")}
    assert sorted(copies) == sorted(core), "a core migration is missing from ./migrations"
    for name, text in core.items():
        assert copies[name].read_text(encoding="utf-8") == text, f"{name} drifted: copy it again"


def test_conformance_in_process(host: FastAPI) -> None:
    report = suite(app=host, token=TOKEN, raise_on_failure=False)
    print("\n".join(report.lines()))
    assert report.ok
    # What this host's policy makes moot is skipped with a reason; links and MCP all run.
    assert {o.name for o in report.of("skipped")} == EXPECTED_SKIPS


@pytest.fixture
def live_url(host: FastAPI) -> Iterator[str]:
    server = uvicorn.Server(
        uvicorn.Config(host, host="127.0.0.1", port=0, log_level="warning", lifespan="on")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    while not server.started:
        if not thread.is_alive():
            raise RuntimeError("uvicorn exited before it started")
        thread.join(0.02)
    try:
        yield f"http://127.0.0.1:{server.servers[0].sockets[0].getsockname()[1]}"
    finally:
        server.should_exit = True
        thread.join(10)


def test_conformance_over_http(live_url: str) -> None:
    report = suite(base_url=live_url, token=TOKEN, raise_on_failure=False)
    print("\n".join(report.lines()))
    assert report.ok


def test_psycopg_adapter_runs_the_kit(fakedb: FakeDb, arpn_pg: Any, tmp_path: Path) -> None:
    """The example's own `PsycopgDb`, not the test double, serves a full run."""
    info = arpn_pg.info
    dsn = f"host={info.host} port={info.port} dbname={info.dbname} user={info.user}"
    db = PsycopgDb(dsn)
    assert migrate(db)  # applies ./migrations to the empty test database
    app = make_app(build_host_config(db, tmp_path / "blobs", {TOKEN: "example-user"}))
    report = suite(app=app, token=TOKEN, raise_on_failure=False)
    print("\n".join(report.lines()))
    assert report.ok
