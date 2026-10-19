"""DDL access. Owner: C1a (ga-mxal.25).

`ddl()` returns the text of `arp_notes/sql/001_notes.sql` (ADR A.1 core tables + K§1). A host
copies it into its own migration at the pinned version (ADR §9.4, §9.6 rule 7); the package never
applies it at runtime.
"""

from __future__ import annotations

from importlib import resources


def ddl() -> str:
    """The core DDL, idempotent: every statement is guarded by IF NOT EXISTS."""
    return (resources.files("arp_notes") / "sql" / "001_notes.sql").read_text(encoding="utf-8")
