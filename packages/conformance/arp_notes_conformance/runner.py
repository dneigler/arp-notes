"""Conformance: run the checks and report. Owner: C7a ga-mxal.14.

`suite(...)` is the entry point hosts call from a pytest file; `arp-notes-conformance` (cli.py)
wraps it. Every suite module publishes a `CHECKS` list of `(name, fn(harness))`; this runner reads
them in order, so C7b's modules join the run by defining `CHECKS` and nothing else.
"""

from __future__ import annotations

import importlib
import os
import traceback
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any

from .harness import (
    DEFAULT,
    DEFAULT_PREFIX,
    CheckFailed,
    CheckSkipped,
    Fixture,
    Harness,
    Schemas,
    connect,
    load_fixture,
)

SUITE_MODULES = (
    "suite_core",
    "suite_attach",
    "suite_enrich",
    "suite_export",
    "suite_mcp",
    "suite_hygiene",
)


@dataclass
class Outcome:
    name: str
    status: str  # 'passed' | 'failed' | 'skipped' | 'error'
    detail: str = ""


@dataclass
class Report:
    outcomes: list[Outcome] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def of(self, status: str) -> list[Outcome]:
        return [o for o in self.outcomes if o.status == status]

    @property
    def ok(self) -> bool:
        return not self.of("failed") and not self.of("error")

    def lines(self) -> list[str]:
        marks = {"passed": "PASS", "failed": "FAIL", "skipped": "SKIP", "error": "ERROR"}
        out = [
            f"{marks[o.status]:5} {o.name}" + (f"\n        {o.detail}" if o.detail else "")
            for o in self.outcomes
        ]
        out += [f"WARN  {w}" for w in self.warnings]
        counts = ", ".join(
            f"{len(self.of(s))} {s}" for s in ("passed", "failed", "error", "skipped")
        )
        return [*out, f"{len(self.outcomes)} checks: {counts}"]

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "checks": [vars(o) for o in self.outcomes],
            "warnings": self.warnings,
        }

    def raise_for_failures(self) -> None:
        if not self.ok:
            raise ConformanceFailure("\n".join(self.lines()))


class ConformanceFailure(AssertionError):
    """The host failed at least one check; the message is the whole report."""


def collect(only: Iterable[str] | None = None) -> list[tuple[str, Callable[[Harness], None]]]:
    """Every published check, in order. `only` keeps names equal to or under one of its entries
    (`sync` keeps every `sync.*`)."""
    checks: list[tuple[str, Callable[[Harness], None]]] = []
    for module in SUITE_MODULES:
        checks += getattr(importlib.import_module(f"{__package__}.{module}"), "CHECKS", [])
    wanted = list(only or [])
    if wanted:
        checks = [c for c in checks if any(c[0] == w or c[0].startswith(w + ".") for w in wanted)]
        if not checks:
            raise ValueError(f"no check matches {wanted}")
    return checks


def run(harness: Harness, checks: Sequence[tuple[str, Callable[[Harness], None]]]) -> Report:
    report = Report()
    for name, fn in checks:
        harness.begin()
        try:
            fn(harness)
            report.outcomes.append(Outcome(name, "passed"))
        except CheckSkipped as skipped:
            report.outcomes.append(Outcome(name, "skipped", str(skipped)))
        except CheckFailed as failed:
            report.outcomes.append(Outcome(name, "failed", str(failed)))
        except Exception:  # a crash in the kit or an unreadable response, never a pass
            report.outcomes.append(Outcome(name, "error", traceback.format_exc(limit=4).strip()))
    report.warnings += harness.cleanup()
    return report


def suite(
    *,
    app: Any = None,
    base_url: str | None = None,
    token: str | None = None,
    fixture: Fixture | str | os.PathLike[str] | Any = DEFAULT,
    api_prefix: str = DEFAULT_PREFIX,
    schemas_dir: str | os.PathLike[str] | None = None,
    only: Iterable[str] | None = None,
    raise_on_failure: bool = True,
) -> Report:
    """Run the kit against an ASGI `app` or a live `base_url` (exactly one), as the user `token`.

    Raises `ConformanceFailure` (an AssertionError carrying the report) unless
    `raise_on_failure=False`. Safe on a live host: it works in its own workspace and deletes
    what it made.
    """
    if not token:
        raise ValueError("token= is required: the Bearer token of the user the kit runs as")
    schemas = Schemas(schemas_dir)
    fixture_ = load_fixture(fixture)
    checks = collect(only)
    with connect(app=app, base_url=base_url) as client:
        harness = Harness(client, token=token, fixture=fixture_, schemas=schemas, prefix=api_prefix)
        report = run(harness, checks)
    if raise_on_failure:
        report.raise_for_failures()
    return report
