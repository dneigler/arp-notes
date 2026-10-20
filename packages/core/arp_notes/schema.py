"""DDL access. Owner: C1a (ga-mxal.25).

`ddl()` returns the text of `arp_notes/sql/001_notes.sql` (ADR A.1 core tables + K§1). A host
copies it into its own migration at the pinned version (ADR §9.4, §9.6 rule 7); the package never
applies it at runtime.

Later numbered files (`002_*.sql`, ...) are deltas for a database that already applied 001;
`migrations()` returns them in order.
"""

from __future__ import annotations

from importlib import resources

_SQL = resources.files("arp_notes") / "sql"


def ddl() -> str:
    """The core DDL, idempotent: every statement is guarded by IF NOT EXISTS."""
    return (_SQL / "001_notes.sql").read_text(encoding="utf-8")


def migrations() -> list[tuple[str, str]]:
    """(file name, text) of every numbered SQL file after 001, in order. Each is idempotent."""
    files = sorted(
        (f for f in _SQL.iterdir() if f.name.endswith(".sql") and f.name[:3] != "001"),
        key=lambda f: f.name,
    )
    return [(f.name, f.read_text(encoding="utf-8")) for f in files]
