"""FakeDb: a `ports.Db` over a throwaway Postgres, for tests (K§7, C1a ga-mxal.25).

The core targets Postgres (JSONB, partial indexes, SERIAL), so tests run against the real thing:
`pytest-postgresql` starts a private server once per session and clones a fresh database for each
test. Use it from a conftest::

    pytest_plugins = ["arp_notes.testing.fakedb"]

    def test_something(notes_db):          # DDL already applied
        notes_db.run("INSERT INTO notes (user_id, title) VALUES (%s, %s)", ["u1", "Hello"])

Fixtures
- `fakedb`: a `FakeDb` on an empty database.
- `notes_db`: a `FakeDb` with `arp_notes.schema.ddl()` applied.

Needs the `testing` extra (`pip install arp-notes-core[testing]`) and a local Postgres install
(CI uses 16). The `pg_ctl` binary is found through `$ARPN_PG_CTL`, then `$PATH`, then the usual
install directories.
"""

from __future__ import annotations

import glob
import os
import re
import shutil
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from typing import Any

import psycopg
import pytest
from psycopg.rows import dict_row
from pytest_postgresql import factories

from arp_notes.schema import ddl, migrations

_FALLBACK_GLOBS = (
    "/usr/lib/postgresql/*/bin/pg_ctl",  # Debian / Ubuntu (GitHub runners)
    "/opt/homebrew/opt/postgresql@*/bin/pg_ctl",  # Homebrew, Apple silicon
    "/usr/local/opt/postgresql@*/bin/pg_ctl",  # Homebrew, Intel
)


def _major_version(path: str) -> int:
    match = re.search(r"postgresql(?:@|/)(\d+)", path)
    return int(match.group(1)) if match else 0


def find_pg_ctl() -> str | None:
    """Locate pg_ctl: `$ARPN_PG_CTL`, then PATH, then the newest known install. None if absent.

    None leaves pytest-postgresql on its own default (`--postgresql-exec`), which then fails at
    fixture start with its usual message.
    """
    explicit = os.environ.get("ARPN_PG_CTL")
    if explicit:
        return explicit
    on_path = shutil.which("pg_ctl")
    if on_path:
        return on_path
    found = [path for pattern in _FALLBACK_GLOBS for path in glob.glob(pattern)]
    return max(found, key=_major_version) if found else None


def _format_placeholders(sql: str) -> str:
    """Turn '?' placeholders into psycopg's '%s' and escape literal '%'.

    Quoted strings, quoted identifiers and `--` comments are left alone, so a '?' inside a string
    literal survives. This lets core SQL use either style, as ADR §9.2 allows.
    """
    out: list[str] = []
    i, n = 0, len(sql)
    while i < n:
        ch = sql[i]
        if ch in ("'", '"'):
            end = i + 1
            while end < n:
                if sql[end] == ch:
                    if end + 1 < n and sql[end + 1] == ch:  # doubled quote escapes itself
                        end += 2
                        continue
                    break
                end += 1
            out.append(sql[i : end + 1].replace("%", "%%"))
            i = end + 1
        elif sql.startswith("--", i):
            end = sql.find("\n", i)
            end = n if end < 0 else end
            out.append(sql[i:end].replace("%", "%%"))
            i = end
        elif ch == "?":
            out.append("%s")
            i += 1
        elif ch == "%":
            # An existing '%s' stays a placeholder; any other '%' is a literal.
            if sql.startswith("%s", i):
                out.append("%s")
                i += 2
            else:
                out.append("%%")
                i += 1
        else:
            out.append(ch)
            i += 1
    return "".join(out)


class FakeDb:
    """`ports.Db` over a psycopg 3 connection. Rows come back as dicts.

    Statements outside `transaction()` autocommit. Inside it they share one transaction, which
    commits on a clean exit and rolls back on an exception; nested blocks become savepoints.
    Accepts both '?' and '%s' placeholders.
    """

    def __init__(self, conn: psycopg.Connection[Any]) -> None:
        conn.autocommit = True
        self._conn = conn

    def run(self, sql: str, params: Sequence[Any] = ()) -> list[dict[str, Any]]:
        values = tuple(params)
        # psycopg types queries as LiteralString; ours are built at runtime by design.
        query: Any = _format_placeholders(sql) if values else sql
        with self._conn.cursor(row_factory=dict_row) as cur:
            cur.execute(query, values or None)
            return list(cur.fetchall()) if cur.description else []

    @contextmanager
    def transaction(self) -> Iterator[FakeDb]:
        with self._conn.transaction():
            yield self

    def apply_ddl(self) -> None:
        """Apply `schema.ddl()` then every later migration. Safe to repeat: all are idempotent."""
        self.run(ddl())
        for _name, text in migrations():
            self.run(text)


# A private server per session on a random port, and a fresh database per test. The names are
# prefixed so they never collide with pytest-postgresql's own default fixtures.
arpn_pg_proc = factories.postgresql_proc(executable=find_pg_ctl())
arpn_pg = factories.postgresql("arpn_pg_proc")


@pytest.fixture
def fakedb(arpn_pg: psycopg.Connection[Any]) -> FakeDb:
    return FakeDb(arpn_pg)


@pytest.fixture
def notes_db(fakedb: FakeDb) -> FakeDb:
    fakedb.apply_ddl()
    return fakedb
