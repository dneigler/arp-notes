"""`arp-notes-conformance`: run the kit against a host from the command line.

Owner: C7a ga-mxal.14.

    arp-notes-conformance --base-url https://notes.example.com --token $TOKEN
    arp-notes-conformance --asgi myapp.main:app --token dev-token --only sync
"""

from __future__ import annotations

import argparse
import importlib
import json
import os
import sys
from typing import Any

from .harness import DEFAULT_PREFIX
from .runner import collect, suite


def load_asgi(spec: str) -> Any:
    """`pkg.module:attr` -> the ASGI app. A trailing `()` calls attr first (an app factory)."""
    module_name, _, attr = spec.partition(":")
    if not module_name or not attr:
        raise SystemExit(f"--asgi wants module:attr, got {spec!r}")
    factory = attr.endswith("()")
    app = getattr(importlib.import_module(module_name), attr.removesuffix("()"))
    return app() if factory else app


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="arp-notes-conformance", description="Black-box conformance kit for arp-notes hosts."
    )
    where = parser.add_mutually_exclusive_group(required=True)
    where.add_argument("--base-url", help="origin of a live host, e.g. https://notes.example.com")
    where.add_argument("--asgi", metavar="MODULE:ATTR", help="an ASGI app, run in-process")
    parser.add_argument("--token", default=os.environ.get("ARP_NOTES_TOKEN"), help="Bearer token")
    parser.add_argument("--api-prefix", default=DEFAULT_PREFIX, help="default: %(default)s")
    parser.add_argument("--fixture", help="a fixture directory or fixture.json (default: bundled)")
    parser.add_argument("--schemas", help="a copy of arp_notes/schemas (default: arp-notes-core's)")
    parser.add_argument("--only", action="append", help="a check or group name; repeatable")
    parser.add_argument("--json", action="store_true", help="print the report as JSON")
    parser.add_argument("--list", action="store_true", help="list the checks and exit")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.list:
        print("\n".join(name for name, _ in collect()), file=sys.stdout)
        return 0
    if not args.token:
        print("error: pass --token or set ARP_NOTES_TOKEN", file=sys.stderr)
        return 2
    try:
        report = suite(
            app=load_asgi(args.asgi) if args.asgi else None,
            base_url=args.base_url,
            token=args.token,
            fixture=args.fixture or None,
            api_prefix=args.api_prefix,
            schemas_dir=args.schemas,
            only=args.only,
            raise_on_failure=False,
        )
    except (FileNotFoundError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(report.as_dict(), indent=2) if args.json else "\n".join(report.lines()))
    return 0 if report.ok else 1


if __name__ == "__main__":
    sys.exit(main())
