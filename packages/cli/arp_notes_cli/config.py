"""`arp-notes config` and `arp-notes login`: app registry (config.toml) and API tokens.

Owner: CLI-a ga-mxal.6 (ADR A.5).

Apps are registered by name in `~/.config/arp-notes/config.toml`:

    [apps.pt]
    url = "https://practicetracker.arpinator.com"

The token never goes in that file. It comes from `ARP_NOTES_TOKEN`, else the OS keyring (the
optional `keyring` extra).
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import re
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from arp_notes_cli.registry import Subparsers

CONFIG_DIR_ENV = "ARP_NOTES_CONFIG_DIR"
TOKEN_ENV = "ARP_NOTES_TOKEN"
KEYRING_SERVICE = "arp-notes"
DEFAULT_API_PREFIX = "/api/v1"

_BARE_KEY = re.compile(r"^[A-Za-z0-9_-]+$")


class ConfigError(Exception):
    """A problem with the user's configuration (unknown app, bad URL, no token)."""


@dataclass(frozen=True)
class AppConfig:
    name: str
    url: str
    # The A.2 routes live under `<url><api_prefix>`. A host that mounts them elsewhere sets
    # `api_prefix` on its `[apps.<name>]` table.
    api_prefix: str = DEFAULT_API_PREFIX

    @property
    def api_base(self) -> str:
        return self.url + self.api_prefix


def config_dir() -> Path:
    override = os.environ.get(CONFIG_DIR_ENV)
    if override:
        return Path(override).expanduser()
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg).expanduser() if xdg else Path.home() / ".config"
    return base / "arp-notes"


def config_path() -> Path:
    return config_dir() / "config.toml"


def normalize_url(url: str) -> str:
    cleaned = url.strip().rstrip("/")
    if not re.match(r"^https?://[^/\s]+", cleaned):
        raise ConfigError(f"not a valid http(s) URL: {url!r}")
    return cleaned


def normalize_prefix(prefix: str) -> str:
    cleaned = "/" + prefix.strip().strip("/")
    return "" if cleaned == "/" else cleaned


def _load_raw() -> dict[str, Any]:
    path = config_path()
    if not path.exists():
        return {}
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except (tomllib.TOMLDecodeError, OSError) as exc:
        raise ConfigError(f"cannot read {path}: {exc}") from exc


def load_apps() -> dict[str, AppConfig]:
    apps: dict[str, AppConfig] = {}
    table = _load_raw().get("apps", {})
    if not isinstance(table, dict):
        raise ConfigError(f"{config_path()}: [apps] must be a table")
    for name, entry in table.items():
        if not isinstance(entry, dict) or not isinstance(entry.get("url"), str):
            raise ConfigError(f"{config_path()}: [apps.{name}] needs a string `url`")
        prefix = entry.get("api_prefix", DEFAULT_API_PREFIX)
        if not isinstance(prefix, str):
            raise ConfigError(f"{config_path()}: [apps.{name}] api_prefix must be a string")
        apps[name] = AppConfig(
            name=name, url=normalize_url(entry["url"]), api_prefix=normalize_prefix(prefix)
        )
    return apps


def get_app(name: str) -> AppConfig:
    apps = load_apps()
    if name not in apps:
        known = ", ".join(sorted(apps)) or "none configured"
        raise ConfigError(
            f"unknown app {name!r} ({known}). Register it: arp-notes login --app {name} --url URL"
        )
    return apps[name]


def _toml_key(key: str) -> str:
    return key if _BARE_KEY.match(key) else json.dumps(key)


def _toml_scalar(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return str(value)
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)  # a JSON string is a valid TOML basic string
    raise ConfigError(f"cannot write a {type(value).__name__} value to config.toml")


def _render(raw: dict[str, Any]) -> str:
    lines: list[str] = []
    for key, value in raw.items():
        if not isinstance(value, dict):
            lines.append(f"{_toml_key(key)} = {_toml_scalar(value)}")
    for key, value in raw.items():
        if not isinstance(value, dict):
            continue
        for sub_key, sub in value.items():
            if isinstance(sub, dict):
                lines += ["", f"[{_toml_key(key)}.{_toml_key(sub_key)}]"]
                lines += [f"{_toml_key(k)} = {_toml_scalar(v)}" for k, v in sub.items()]
    return "\n".join(lines).lstrip("\n") + "\n"


def save_app(app: AppConfig) -> None:
    """Add or replace `[apps.<name>]`, keeping every other app. Comments are not preserved."""
    raw = _load_raw()
    apps = raw.setdefault("apps", {})
    entry: dict[str, Any] = {"url": normalize_url(app.url)}
    prefix = normalize_prefix(app.api_prefix)
    if prefix != DEFAULT_API_PREFIX:
        entry["api_prefix"] = prefix
    apps[app.name] = entry
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_render(raw), encoding="utf-8")


def _keyring() -> Any | None:
    try:
        import keyring  # type: ignore[import-not-found]  # optional extra
    except ImportError:
        return None
    return keyring


def load_token(app: str) -> str | None:
    env = os.environ.get(TOKEN_ENV)
    if env:
        return env.strip()
    kr = _keyring()
    if kr is None:
        return None
    try:
        token = kr.get_password(KEYRING_SERVICE, app)
    except Exception:  # a locked or missing keyring backend must not break the CLI
        return None
    return token or None


def store_token(app: str, token: str) -> bool:
    """Save the token in the keyring. False when no keyring is available."""
    kr = _keyring()
    if kr is None:
        return False
    try:
        kr.set_password(KEYRING_SERVICE, app, token)
    except Exception:
        return False
    return True


def add_app_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--app", required=True, help="app name from config.toml, e.g. pt")


def _read_token(args: argparse.Namespace) -> str:
    if args.token_stdin:
        token = sys.stdin.readline().strip()
    elif os.environ.get(TOKEN_ENV):
        token = os.environ[TOKEN_ENV].strip()
    else:
        token = getpass.getpass(f"API token for {args.app}: ").strip()
    if not token:
        raise ConfigError("no token given")
    return token


def _cmd_login(args: argparse.Namespace) -> int:
    from arp_notes_cli.client import ClientError, NotesClient

    try:
        app = AppConfig(
            name=args.app,
            url=normalize_url(args.url),
            api_prefix=normalize_prefix(args.api_prefix),
        )
        token = _read_token(args)
        if not args.no_verify:
            with NotesClient(app, token) as client:
                caps = client.capabilities()
            print(f"{app.name}: {app.url} speaks protocol {caps['protocol']}")
        save_app(app)
    except ConfigError as exc:
        print(f"arp-notes login: {exc}", file=sys.stderr)
        return 2
    except ClientError as exc:
        print(f"arp-notes login: {exc}", file=sys.stderr)
        return 1
    if store_token(app.name, token):
        print(f"token stored in the OS keyring; app saved to {config_path()}")
    else:
        print(
            f"app saved to {config_path()}. No keyring available "
            f"(pip install 'arp-notes[keyring]'), so the token was not stored: "
            f"export {TOKEN_ENV} for each run.",
            file=sys.stderr,
        )
    return 0


def _cmd_config(args: argparse.Namespace) -> int:
    if args.config_command == "path":
        print(config_path())
        return 0
    try:
        apps = load_apps()
    except ConfigError as exc:
        print(f"arp-notes config: {exc}", file=sys.stderr)
        return 2
    rows = [
        {
            "app": a.name,
            "url": a.url,
            "api_prefix": a.api_prefix,
            "token": "set" if load_token(a.name) else "missing",
        }
        for a in apps.values()
    ]
    if args.json:
        print(json.dumps({"path": str(config_path()), "apps": rows}, indent=2))
    else:
        print(f"config: {config_path()}")
        for row in rows:
            print(f"  {row['app']}: {row['url']}{row['api_prefix']} (token {row['token']})")
        if not rows:
            print("  no apps configured. Run: arp-notes login --app NAME --url URL")
    return 0


def register(subparsers: Subparsers) -> None:
    login = subparsers.add_parser(
        "login", help="Register an app and store its API token.", description=__doc__
    )
    login.add_argument("--app", required=True, help="name to register the app under, e.g. pt")
    login.add_argument("--url", required=True, help="the host's base URL")
    login.add_argument(
        "--api-prefix",
        default=DEFAULT_API_PREFIX,
        help=f"where the host mounts the notes routes (default {DEFAULT_API_PREFIX})",
    )
    login.add_argument(
        "--token-stdin",
        action="store_true",
        help=f"read the token from one line of stdin (else {TOKEN_ENV}, else prompt)",
    )
    login.add_argument(
        "--no-verify", action="store_true", help="save without calling GET /notes/capabilities"
    )
    login.set_defaults(func=_cmd_login)

    config = subparsers.add_parser(
        "config", help="Show configured apps (config.toml). Tokens are never printed."
    )
    config.add_argument("config_command", nargs="?", choices=["show", "path"], default="show")
    config.add_argument("--json", action="store_true")
    config.set_defaults(func=_cmd_config)
