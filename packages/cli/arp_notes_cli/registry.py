"""Subcommand registry plumbing (C0). Lanes use add_stub() until they have a real handler."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from typing import Any

Subparsers = Any  # argparse._SubParsersAction is private

NOT_IMPLEMENTED_EXIT = 2


def not_implemented(name: str) -> Callable[[argparse.Namespace], int]:
    def handler(args: argparse.Namespace) -> int:
        print(f"arp-notes {name}: not implemented", file=sys.stderr)
        return NOT_IMPLEMENTED_EXIT

    return handler


def add_stub(subparsers: Subparsers, name: str, help_text: str) -> argparse.ArgumentParser:
    """Register `name` as a subcommand that accepts any arguments and reports not implemented."""
    parser = subparsers.add_parser(name, help=help_text, description=help_text)
    parser.add_argument("rest", nargs=argparse.REMAINDER, help=argparse.SUPPRESS)
    parser.set_defaults(func=not_implemented(name))
    return parser
