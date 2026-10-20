"""arp-notes conformance kit: drives any implementation over HTTP (A.2) and, in C7b, MCP (A.3).

Owners: C7a (ga-mxal.14) for harness, suite_core and the runner; C7b (ga-mxal.38) for the rest.

    from arp_notes_conformance import suite

    suite(app=app, token=TOKEN)                    # in-process ASGI
    suite(base_url="https://...", token=TOKEN)     # any stack, over the wire
"""

from .harness import DEFAULT, Document, Fixture, LinkTarget, load_fixture
from .runner import ConformanceFailure, Outcome, Report, suite

__all__ = [
    "DEFAULT",
    "ConformanceFailure",
    "Document",
    "Fixture",
    "LinkTarget",
    "Outcome",
    "Report",
    "load_fixture",
    "suite",
]
