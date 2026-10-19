"""arp-notes entrypoint and subcommand registry (C0, ga-mxal.5).

Every module in this package that defines `register(subparsers)` is imported and asked to add its
subcommands, so a lane adds a command by editing only the modules it owns, never this file.
"""

from __future__ import annotations

import argparse
import importlib
import pkgutil
import sys
from collections.abc import Sequence

import arp_notes_cli

_NOT_COMMAND_MODULES = {"main", "registry"}


def _command_modules() -> list[str]:
    return sorted(
        info.name
        for info in pkgutil.iter_modules(arp_notes_cli.__path__)
        if info.name not in _NOT_COMMAND_MODULES and not info.name.startswith("_")
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="arp-notes",
        description="Scan, sync and pull notes between a notes tool and an arp-notes host app.",
    )
    parser.add_argument("--version", action="version", version=arp_notes_cli.__version__)
    subparsers = parser.add_subparsers(dest="command", metavar="<command>")
    for name in _command_modules():
        module = importlib.import_module(f"arp_notes_cli.{name}")
        register = getattr(module, "register", None)
        if register is not None:
            register(subparsers)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if getattr(args, "func", None) is None:
        parser.print_help(sys.stderr)
        return 2
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
