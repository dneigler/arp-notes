"""Every K§7 module exists and imports, so lanes can land in any order."""

from __future__ import annotations

import importlib
import pkgutil

import arp_notes
import pytest

# K§7, verbatim module list. A missing stub fails here, not in some other lane's import.
K7_MODULES = [
    "arp_notes.ports",
    "arp_notes.anchors",
    "arp_notes.config",
    "arp_notes.schema",
    "arp_notes.models",
    "arp_notes.repo",
    "arp_notes.sync",
    "arp_notes.attachments",
    "arp_notes.storage.disk",
    "arp_notes.storage.postgres",
    "arp_notes.storage.s3",
    "arp_notes.enrich",
    "arp_notes.extract",
    "arp_notes.judges",
    "arp_notes.review",
    "arp_notes.export",
    "arp_notes.fastapi",
    "arp_notes.mcp",
    "arp_notes.hygiene",
    "arp_notes.hygiene.detect",
    "arp_notes.hygiene.routes",
    "arp_notes.hygiene.tools",
    "arp_notes.hygiene.fixes",
]


@pytest.mark.parametrize("name", K7_MODULES)
def test_k7_module_imports(name: str) -> None:
    importlib.import_module(name)


def test_every_module_in_the_package_imports() -> None:
    names = [m.name for m in pkgutil.walk_packages(arp_notes.__path__, "arp_notes.")]
    assert set(K7_MODULES) <= set(names)
    for name in names:
        importlib.import_module(name)


def test_protocol_version() -> None:
    assert arp_notes.PROTOCOL_VERSION == 1
