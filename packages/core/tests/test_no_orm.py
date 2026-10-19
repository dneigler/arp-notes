"""The core is ORM-free and app-agnostic (ADR §9.2): no ORM import anywhere in arp_notes."""

from __future__ import annotations

import ast
from pathlib import Path

import arp_notes

ORM_ROOTS = {
    "sqlalchemy",
    "sqlmodel",
    "peewee",
    "django",
    "pony",
    "tortoise",
    "ormar",
    "orator",
    "mongoengine",
    "sqlobject",
    "databases",
    "alembic",
}


def test_no_module_imports_an_orm() -> None:
    root = Path(arp_notes.__file__).parent
    offenders: list[str] = []
    for path in root.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text("utf-8"))):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                names = [node.module]
            offenders += [
                f"{path.relative_to(root)}: {n}" for n in names if n.split(".")[0] in ORM_ROOTS
            ]
    assert offenders == []
