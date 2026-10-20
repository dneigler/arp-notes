import importlib

import pytest

MODULES = [
    "arp_notes_conformance",
    "arp_notes_conformance.harness",
    "arp_notes_conformance.runner",
    "arp_notes_conformance.cli",
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


def test_suite_wants_exactly_one_target_and_a_token() -> None:
    from arp_notes_conformance import suite

    with pytest.raises(ValueError, match="token"):
        suite()
    with pytest.raises(ValueError, match="exactly one"):
        suite(token="t")
