"""Shared helpers for CLI tests: a synthetic vault, schema-checked manifest stubs, an app config."""

from __future__ import annotations

import hashlib
import json
from importlib import resources
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx
from jsonschema import Draft202012Validator

APP_URL = "https://notes.example.test"
API = APP_URL + "/api/v1"
TOKEN = "pt_test_token"

PNG_A = b"\x89PNG\r\n\x1a\n" + b"synthetic image A"
PNG_B = b"\x89PNG\r\n\x1a\n" + b"synthetic image B"


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _core_json(*parts: str) -> Any:
    root = resources.files("arp_notes.schemas")
    for part in parts:
        root = root / part  # type: ignore[assignment]
    return json.loads(root.read_text(encoding="utf-8"))  # type: ignore[attr-defined]


_MANIFEST_SCHEMA = Draft202012Validator(_core_json("manifest_page.json"))
_CAPABILITIES_SCHEMA = Draft202012Validator(_core_json("capabilities.json"))


def manifest_row(
    doc_id: str,
    path: str,
    content: bytes,
    attachments: list[bytes] | None = None,
    *,
    deleted_at: str | None = None,
) -> dict[str, Any]:
    return {
        "source_doc_id": doc_id,
        "source_path": path,
        "content_hash": sha(content),
        "attachments": sorted({sha(a) for a in attachments or []}),
        "last_synced_at": "2026-10-18T14:30:00",
        "deleted_at": deleted_at,
    }


def manifest_page(
    rows: list[dict[str, Any]], next_after: str | None = None, protocol: int = 1
) -> dict[str, Any]:
    page = {"protocol": protocol, "items": rows, "next_after": next_after}
    _MANIFEST_SCHEMA.validate(page)
    return page


def capabilities(protocol: int = 1) -> dict[str, Any]:
    caps = _core_json("examples", "Capabilities.json")
    _CAPABILITIES_SCHEMA.validate(caps)  # the stub is the core's own example; only protocol varies
    caps["protocol"] = protocol
    return caps


def write(vault: Path, rel: str, data: str | bytes) -> Path:
    path = vault / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(data, str):
        path.write_text(data, encoding="utf-8")
    else:
        path.write_bytes(data)
    return path


def make_vault(tmp_path: Path, name: str = "Dave2025") -> Path:
    vault = tmp_path / name
    (vault / ".obsidian").mkdir(parents=True)
    return vault


@pytest.fixture
def config_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """An isolated config dir with app `pt` registered and a token in the environment."""
    home = tmp_path / "config"
    monkeypatch.setenv("ARP_NOTES_CONFIG_DIR", str(home))
    monkeypatch.setenv("ARP_NOTES_TOKEN", TOKEN)
    home.mkdir()
    (home / "config.toml").write_text(f'[apps.pt]\nurl = "{APP_URL}"\n', encoding="utf-8")
    return home


@pytest.fixture
def api() -> Any:
    with respx.mock(assert_all_called=False) as router:
        yield router


def serve_manifest(router: respx.MockRouter, rows: list[dict[str, Any]]) -> respx.Route:
    return router.get(f"{API}/notes/sync/manifest").mock(
        return_value=httpx.Response(200, json=manifest_page(rows))
    )
