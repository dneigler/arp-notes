"""The subcommand registry discovers every command module (C0)."""

from __future__ import annotations

import argparse

import pytest
from arp_notes_cli.main import build_parser, main
from arp_notes_cli.registry import add_stub

IMPLEMENTED = [
    "config", "login", "scan", "status", "capabilities",  # CLI-a, ga-mxal.6
    "sync", "verify", "tombstone",  # CLI-b, ga-mxal.36
    "pull",  # CLI-c, ga-mxal.37
    "conformance",  # C7b, ga-mxal.38
    "init",  # C9, ga-mxal.23
]  # fmt: skip


def _registered() -> set[str]:
    parser = build_parser()
    for action in parser._actions:  # noqa: SLF001
        choices = getattr(action, "choices", None)
        if isinstance(choices, dict) and "scan" in choices:
            return set(choices)
    raise AssertionError("no subcommands registered")


def test_all_subcommands_are_registered() -> None:
    assert set(IMPLEMENTED) <= _registered()


def test_a_stub_prints_not_implemented_and_exits_2(capsys: pytest.CaptureFixture[str]) -> None:
    """`add_stub` is how a lane registers a command before its handler lands (every one has)."""
    parser = argparse.ArgumentParser(prog="arp-notes")
    add_stub(parser.add_subparsers(), "later", "A command whose lane has not landed.")
    args = parser.parse_args(["later", "my-app", "--anything"])
    assert args.func(args) == 2
    assert "arp-notes later: not implemented" in capsys.readouterr().err


def test_no_command_prints_help_and_exits_2(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([]) == 2
    assert "usage: arp-notes" in capsys.readouterr().err


def test_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert capsys.readouterr().out.strip() == "0.1.0rc2"
