import importlib

import pytest

MODULES = [
    "arp_notes_conformance",
    "arp_notes_conformance.harness",
    "arp_notes_conformance.suite_core",
    "arp_notes_conformance.suite_attach",
    "arp_notes_conformance.suite_enrich",
    "arp_notes_conformance.suite_export",
    "arp_notes_conformance.suite_mcp",
    "arp_notes_conformance.suite_hygiene",
]


@pytest.mark.parametrize("name", MODULES)
def test_module_imports(name: str) -> None:
    importlib.import_module(name)


def test_suite_entrypoint_is_a_stub() -> None:
    from arp_notes_conformance import suite

    with pytest.raises(NotImplementedError):
        suite()
