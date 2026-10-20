"""`arp-notes conformance` / `verify --conformance` against a live (uvicorn) host (C7b)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from arp_notes_cli.main import main
from ref_host import TOKEN


@pytest.fixture
def app_config(live_url: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    """An `[apps.ref]` entry for the live host, and its token in the environment."""
    config = tmp_path / "config"
    config.mkdir()
    (config / "config.toml").write_text(f'[apps.ref]\nurl = "{live_url}"\n', encoding="utf-8")
    monkeypatch.setenv("ARP_NOTES_CONFIG_DIR", str(config))
    monkeypatch.setenv("ARP_NOTES_TOKEN", TOKEN)
    monkeypatch.delenv("ARP_NOTES_MCP_URL", raising=False)
    return "ref"


def report_of(capsys: pytest.CaptureFixture[str]) -> dict[str, dict[str, str]]:
    out = json.loads(capsys.readouterr().out)
    return {c["name"]: c for c in out["checks"]}


def test_conformance_command_runs_the_http_subset(
    app_config: str, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["conformance", "--app", app_config, "--json"]) == 0
    checks = report_of(capsys)
    assert checks["capabilities.shape"]["status"] == "passed"
    assert checks["attachments.upload_roundtrip"]["status"] == "passed"
    assert checks["export.round_trip_app_note"]["status"] == "passed"
    assert checks["hygiene.dismiss_hides_the_issue"]["status"] == "passed"
    # the bundled fixture's entities belong to the reference host: never linked on a live one
    assert checks["entity.notes_by_entity"]["status"] == "skipped"
    assert checks["enrich.confirm_creates_links"]["status"] == "skipped"
    assert "link_target" in checks["entity.notes_by_entity"]["detail"]
    assert checks["mcp.tools_list"]["status"] == "passed"  # the reference host serves /mcp


def test_verify_conformance_is_the_same_run(
    app_config: str, capsys: pytest.CaptureFixture[str]
) -> None:
    assert (
        main(["verify", "--conformance", "--app", app_config, "--json", "--only", "attachments"])
        == 0
    )
    checks = report_of(capsys)
    assert checks and all(name.startswith("attachments.") for name in checks)
    assert checks["attachments.signed_content"]["status"] == "passed"


def test_human_report_names_the_host_and_every_check(
    app_config: str, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["conformance", "--app", app_config, "--only", "export.app_note_markdown"]) == 0
    captured = capsys.readouterr()
    assert "conformance of ref at http://127.0.0.1" in captured.err
    assert "PASS  export.app_note_markdown" in captured.out
    assert "1 checks: 1 passed" in captured.out


def test_list_prints_the_check_names(app_config: str, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["conformance", "--app", app_config, "--list", "--only", "hygiene"]) == 0
    names = capsys.readouterr().out.split()
    assert names and all(n.startswith("hygiene.") for n in names)


def test_a_failing_check_exits_1(
    app_config: str, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ARP_NOTES_MCP_URL", "/not-mcp")  # an explicit URL that is not MCP fails
    assert main(["conformance", "--app", app_config, "--only", "mcp.tools_list"]) == 1
    assert "FAIL  mcp.tools_list" in capsys.readouterr().out


def test_mcp_url_option(app_config: str, capsys: pytest.CaptureFixture[str]) -> None:
    args = ["conformance", "--app", app_config, "--only", "mcp.tools_list", "--json"]
    assert main([*args, "--mcp-url", "/not-mcp"]) == 1
    capsys.readouterr()
    assert main([*args, "--mcp-url", "/mcp"]) == 0


def test_no_token_is_a_configuration_error(
    app_config: str, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("ARP_NOTES_TOKEN")
    monkeypatch.setattr("arp_notes_cli.conformance_cmd.load_token", lambda app: None)
    assert main(["conformance", "--app", app_config]) == 2
    assert "no API token" in capsys.readouterr().err


def test_unknown_app_and_unknown_check_are_configuration_errors(
    app_config: str, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["conformance", "--app", "nope"]) == 2
    assert "unknown app" in capsys.readouterr().err
    assert main(["conformance", "--app", app_config, "--only", "no.such.check"]) == 2
    assert "no check matches" in capsys.readouterr().err


def test_verify_conformance_takes_no_paths_and_verify_still_needs_them(
    app_config: str, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    assert main(["verify", "--conformance", "--app", app_config, str(tmp_path)]) == 2
    assert "takes no paths" in capsys.readouterr().err
    assert main(["verify", "--app", app_config]) == 2
    assert "needs Markdown files" in capsys.readouterr().err
