"""`arp-notes conformance` and `arp-notes verify --conformance`: the kit against a live host.

Owner: C7b ga-mxal.38 (ADR §9.3).

    arp-notes conformance --app pt              # every check that needs nothing of the host's own
    arp-notes verify --conformance --app pt     # the same, as the post-release gate (A.5)

The kit (`arp-notes-conformance`) is black-box, so this only supplies the live host: the app's URL,
API prefix and token from `config.toml`. It runs the HTTP subset: every check that works with
nothing but the protocol. The bundled fixture's `link_target` names entities of the *reference*
host, so on a live host it is left out and the checks that need real entities (links, by-entity,
the recognised document) report themselves as skipped, never as passed. Pass `--fixture DIR` with a
fixture written for the host to run those too. Each run works in its own throw-away workspace and
deletes the notes it made.

MCP mode runs when the host's MCP endpoint answers at `/mcp` (or `--mcp-url`); otherwise those
checks are skipped with the paths tried.

Exit codes: 0 every check passed or was skipped, 1 a check failed, 2 bad input or configuration.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import os
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from arp_notes_cli.client import run_command
from arp_notes_cli.config import ConfigError, add_app_argument, get_app, load_token
from arp_notes_cli.registry import Subparsers

KIT_INSTALL = (
    "pip install 'git+https://github.com/dneigler/arp-notes#subdirectory=packages/conformance'"
)
MCP_URL_ENV = "ARP_NOTES_MCP_URL"


def _kit() -> Any:
    try:
        import arp_notes_conformance
    except ImportError as exc:
        raise ConfigError(
            f"the conformance kit is not installed. Install it with: {KIT_INSTALL}"
        ) from exc
    return arp_notes_conformance


@contextmanager
def _mcp_url(url: str | None) -> Iterator[None]:
    """Point the kit's MCP checks at `url` for the run, restoring the environment after."""
    if url is None:
        yield
        return
    before = os.environ.get(MCP_URL_ENV)
    os.environ[MCP_URL_ENV] = url
    try:
        yield
    finally:
        if before is None:
            os.environ.pop(MCP_URL_ENV, None)
        else:
            os.environ[MCP_URL_ENV] = before


def run_conformance(
    app_name: str,
    *,
    only: list[str] | None = None,
    fixture: str | None = None,
    schemas: str | None = None,
    mcp_url: str | None = None,
    as_json: bool = False,
    list_only: bool = False,
) -> int:
    kit = _kit()
    if list_only:
        from arp_notes_conformance.runner import collect

        print("\n".join(name for name, _ in collect(only)))
        return 0
    app = get_app(app_name)
    token = load_token(app_name)
    if not token:
        raise ConfigError(
            f"no API token for app {app_name!r}: run `arp-notes login --app {app_name} "
            f"--url {app.url}` or set ARP_NOTES_TOKEN"
        )
    if fixture is not None:
        chosen = kit.load_fixture(fixture)
    else:  # the bundled one names the reference host's entities, not this host's
        chosen = dataclasses.replace(
            kit.load_fixture(kit.DEFAULT), link_target=None, recognised_document=None
        )
    try:
        with _mcp_url(mcp_url):
            report = kit.suite(
                base_url=app.url,
                token=token,
                fixture=chosen,
                api_prefix=app.api_prefix,
                schemas_dir=schemas,
                only=only,
                raise_on_failure=False,
            )
    except (FileNotFoundError, ValueError) as exc:  # no schemas, or --only matched nothing
        raise ConfigError(str(exc)) from exc
    if as_json:
        print(json.dumps(report.as_dict(), indent=2, ensure_ascii=False))
    else:
        print(f"conformance of {app.name} at {app.url}{app.api_prefix}", file=sys.stderr)
        print("\n".join(report.lines()))
    return 0 if report.ok else 1


def add_options(parser: argparse.ArgumentParser) -> None:
    """The options both `conformance` and `verify --conformance` take."""
    parser.add_argument("--only", action="append", help="a check or group name; repeatable")
    parser.add_argument(
        "--fixture", help="a fixture directory or fixture.json written for the host"
    )
    parser.add_argument("--schemas", help="a copy of arp_notes/schemas (default: arp-notes-core's)")
    parser.add_argument("--mcp-url", help=f"the host's MCP endpoint (else ${MCP_URL_ENV}, /mcp)")


def run_from_args(args: argparse.Namespace) -> int:
    return run_command(
        "conformance",
        lambda: run_conformance(
            args.app,
            only=args.only,
            fixture=args.fixture,
            schemas=args.schemas,
            mcp_url=args.mcp_url,
            as_json=args.json,
            list_only=getattr(args, "list", False),
        ),
    )


def register(subparsers: Subparsers) -> None:
    parser = subparsers.add_parser(
        "conformance",
        help="Run the conformance kit against a live host.",
        description=(
            "Drive a live host over HTTP with the black-box conformance kit and report every "
            "check. Safe on a live deployment: it works in its own workspace and deletes what "
            "it made. Needs arp-notes-conformance installed."
        ),
    )
    add_app_argument(parser)
    add_options(parser)
    parser.add_argument("--json", action="store_true", help="machine-readable report")
    parser.add_argument("--list", action="store_true", help="list the checks and exit")
    parser.set_defaults(func=run_from_args)
