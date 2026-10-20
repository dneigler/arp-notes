"""config.toml, login, token lookup, the HTTP client and `capabilities` (CLI-a, ga-mxal.6)."""

from __future__ import annotations

import io
import json
import sys
import tomllib
import types
from pathlib import Path
from typing import Any

import httpx
import pytest
from arp_notes_cli import config
from arp_notes_cli.client import ClientError, NotesClient, ProtocolError
from arp_notes_cli.main import main
from cli_support import API, APP_URL, TOKEN, capabilities, manifest_page, manifest_row

# --- config.toml --------------------------------------------------------------------------


def test_config_dir_precedence(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("ARP_NOTES_CONFIG_DIR", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    assert config.config_dir() == tmp_path / "xdg" / "arp-notes"
    monkeypatch.setenv("ARP_NOTES_CONFIG_DIR", str(tmp_path / "explicit"))
    assert config.config_dir() == tmp_path / "explicit"
    monkeypatch.delenv("ARP_NOTES_CONFIG_DIR")
    monkeypatch.delenv("XDG_CONFIG_HOME")
    assert config.config_dir() == Path.home() / ".config" / "arp-notes"


def test_save_and_load_roundtrip_keeps_other_apps(config_home: Path) -> None:
    config.save_app(config.AppConfig("jjf", "https://jjf.example/", "/notes-api/"))
    config.save_app(config.AppConfig("pt", "https://pt.example"))

    apps = config.load_apps()

    assert apps["pt"] == config.AppConfig("pt", "https://pt.example", "/api/v1")
    assert apps["jjf"].api_base == "https://jjf.example/notes-api"
    raw = tomllib.loads((config_home / "config.toml").read_text())
    assert raw["apps"]["pt"] == {"url": "https://pt.example"}  # the default prefix is not written
    assert raw["apps"]["jjf"] == {"url": "https://jjf.example", "api_prefix": "/notes-api"}


def test_get_app_unknown_names_what_is_configured(config_home: Path) -> None:
    with pytest.raises(config.ConfigError, match=r"unknown app 'zz' \(pt\)"):
        config.get_app("zz")


@pytest.mark.parametrize("bad", ["", "ftp://x", "practicetracker.arpinator.com", "https://"])
def test_bad_urls_are_rejected(bad: str) -> None:
    with pytest.raises(config.ConfigError):
        config.normalize_url(bad)


def test_unreadable_config_is_a_config_error(config_home: Path) -> None:
    (config_home / "config.toml").write_text("[apps.pt\n")
    with pytest.raises(config.ConfigError, match="cannot read"):
        config.load_apps()


# --- tokens -------------------------------------------------------------------------------


class _FakeKeyring(types.ModuleType):
    def __init__(self) -> None:
        super().__init__("keyring")
        self.store: dict[tuple[str, str], str] = {}

    def get_password(self, service: str, user: str) -> str | None:
        return self.store.get((service, user))

    def set_password(self, service: str, user: str, password: str) -> None:
        self.store[(service, user)] = password


def test_token_env_beats_keyring(monkeypatch: pytest.MonkeyPatch) -> None:
    kr = _FakeKeyring()
    kr.store[("arp-notes", "pt")] = "from-keyring"
    monkeypatch.setitem(sys.modules, "keyring", kr)
    monkeypatch.setenv("ARP_NOTES_TOKEN", " from-env ")
    assert config.load_token("pt") == "from-env"
    monkeypatch.delenv("ARP_NOTES_TOKEN")
    assert config.load_token("pt") == "from-keyring"
    assert config.load_token("other") is None


def test_no_keyring_means_no_token_and_store_reports_it(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ARP_NOTES_TOKEN", raising=False)
    monkeypatch.setitem(sys.modules, "keyring", None)  # makes `import keyring` raise ImportError
    assert config.load_token("pt") is None
    assert config.store_token("pt", "t") is False


# --- login --------------------------------------------------------------------------------


def test_login_verifies_then_saves_and_stores_token(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    api: Any,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("ARP_NOTES_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.delenv("ARP_NOTES_TOKEN", raising=False)
    kr = _FakeKeyring()
    monkeypatch.setitem(sys.modules, "keyring", kr)
    monkeypatch.setattr("sys.stdin", io.StringIO("pt_secret\n"))
    route = api.get(f"{API}/notes/capabilities").mock(
        return_value=httpx.Response(200, json=capabilities())
    )

    code = main(["login", "--app", "pt", "--url", APP_URL + "/", "--token-stdin"])

    out = capsys.readouterr()
    assert code == 0
    assert route.calls.last.request.headers["authorization"] == "Bearer pt_secret"
    assert kr.store[("arp-notes", "pt")] == "pt_secret"
    assert config.get_app("pt").url == APP_URL
    assert "pt_secret" not in (tmp_path / "cfg" / "config.toml").read_text()
    assert "pt_secret" not in out.out + out.err


def test_login_without_keyring_saves_the_app_and_says_to_export_the_token(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    api: Any,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("ARP_NOTES_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setenv("ARP_NOTES_TOKEN", "pt_env")
    monkeypatch.setitem(sys.modules, "keyring", None)
    api.get(f"{API}/notes/capabilities").mock(return_value=httpx.Response(200, json=capabilities()))

    code = main(["login", "--app", "pt", "--url", APP_URL])

    assert code == 0
    assert "ARP_NOTES_TOKEN" in capsys.readouterr().err
    assert config.get_app("pt").url == APP_URL


def test_login_with_a_rejected_token_saves_nothing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    api: Any,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("ARP_NOTES_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setenv("ARP_NOTES_TOKEN", "pt_bad")
    kr = _FakeKeyring()
    monkeypatch.setitem(sys.modules, "keyring", kr)
    api.get(f"{API}/notes/capabilities").mock(
        return_value=httpx.Response(401, json={"detail": "Invalid token"})
    )

    code = main(["login", "--app", "pt", "--url", APP_URL])

    assert code == 1
    assert "HTTP 401" in capsys.readouterr().err
    assert not (tmp_path / "cfg" / "config.toml").exists()
    assert kr.store == {}


def test_login_no_verify_skips_the_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, api: Any
) -> None:
    monkeypatch.setenv("ARP_NOTES_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setenv("ARP_NOTES_TOKEN", "pt_env")
    monkeypatch.setitem(sys.modules, "keyring", _FakeKeyring())
    route = api.get(f"{API}/notes/capabilities")

    assert main(["login", "--app", "pt", "--url", APP_URL, "--no-verify"]) == 0
    assert not route.called


def test_login_rejects_a_bad_url(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("ARP_NOTES_CONFIG_DIR", str(tmp_path / "cfg"))
    assert main(["login", "--app", "pt", "--url", "not-a-url"]) == 2
    assert "not a valid http(s) URL" in capsys.readouterr().err


def test_config_command_never_prints_the_token(
    config_home: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["config"]) == 0
    out = capsys.readouterr().out
    assert f"pt: {APP_URL}/api/v1 (token set)" in out
    assert TOKEN not in out

    assert main(["config", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["apps"] == [{"app": "pt", "url": APP_URL, "api_prefix": "/api/v1", "token": "set"}]

    assert main(["config", "path"]) == 0
    assert capsys.readouterr().out.strip() == str(config_home / "config.toml")


# --- client -------------------------------------------------------------------------------


def _client(prefix: str = "/api/v1", token: str | None = TOKEN) -> NotesClient:
    return NotesClient(config.AppConfig("pt", APP_URL, prefix), token)


def test_request_builds_the_url_from_url_and_api_prefix(api: Any) -> None:
    route = api.get("https://notes.example.test/custom/notes/capabilities").mock(
        return_value=httpx.Response(200, json=capabilities())
    )
    with _client("/custom") as client:
        assert client.capabilities()["protocol"] == 1
    assert route.called


def test_missing_token_fails_before_any_request(api: Any) -> None:
    route = api.get(f"{API}/notes/capabilities")
    with _client(token=None) as client, pytest.raises(ClientError, match="no API token"):
        client.capabilities()
    assert not route.called


@pytest.mark.parametrize("protocol", [2, "2.0", 0])
def test_capabilities_refuses_another_protocol_major(api: Any, protocol: object) -> None:
    body = capabilities() | {"protocol": protocol}
    api.get(f"{API}/notes/capabilities").mock(return_value=httpx.Response(200, json=body))
    with _client() as client, pytest.raises(ProtocolError, match="speaks protocol 1"):
        client.capabilities()


def test_capabilities_accepts_a_minor_version_string(api: Any) -> None:
    body = capabilities() | {"protocol": "1.2"}
    api.get(f"{API}/notes/capabilities").mock(return_value=httpx.Response(200, json=body))
    with _client() as client:
        assert client.capabilities()["protocol"] == "1.2"


def test_capabilities_rejects_an_answer_that_is_not_ours(api: Any) -> None:
    api.get(f"{API}/notes/capabilities").mock(return_value=httpx.Response(200, json={"ok": True}))
    with _client() as client, pytest.raises(ClientError, match="not an arp-notes answer"):
        client.capabilities()


def test_http_errors_carry_status_detail_and_a_login_hint(api: Any) -> None:
    api.get(f"{API}/notes").mock(return_value=httpx.Response(403, json={"error": "forbidden"}))
    with _client() as client, pytest.raises(ClientError) as raised:
        client.request("GET", "/notes")
    assert raised.value.status == 403
    assert "forbidden" in str(raised.value) and "arp-notes login" in str(raised.value)


def test_network_failure_is_a_client_error(api: Any) -> None:
    api.get(f"{API}/notes/capabilities").mock(side_effect=httpx.ConnectError("refused"))
    with _client() as client, pytest.raises(ClientError, match="cannot reach"):
        client.capabilities()


def test_manifest_paging_stops_on_a_repeated_cursor(api: Any) -> None:
    page = manifest_page([manifest_row("a", "a.md", b"a")], next_after="a")
    api.get(f"{API}/notes/sync/manifest").mock(return_value=httpx.Response(200, json=page))
    with _client() as client, pytest.raises(ClientError, match="does not advance"):
        client.manifest("obsidian", "V")


def test_sync_sources_needs_a_host_that_reports_them(api: Any) -> None:
    api.get(f"{API}/notes").mock(return_value=httpx.Response(200, json={"items": []}))
    with _client() as client, pytest.raises(ClientError, match="--workspace"):
        client.sync_sources()


# --- capabilities command -----------------------------------------------------------------


def test_capabilities_command_prints_the_hosts_answer(
    config_home: Path, api: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    api.get(f"{API}/notes/capabilities").mock(return_value=httpx.Response(200, json=capabilities()))

    code = main(["capabilities", "--app", "pt"])

    assert code == 0
    assert json.loads(capsys.readouterr().out) == capabilities()


def test_capabilities_command_exits_1_on_a_protocol_mismatch(
    config_home: Path, api: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    api.get(f"{API}/notes/capabilities").mock(
        return_value=httpx.Response(200, json=capabilities(protocol=2))
    )

    assert main(["capabilities", "--app", "pt"]) == 1
    assert "protocol" in capsys.readouterr().err
