"""HTTP client for an arp-notes host, and `arp-notes capabilities`.

Owner: CLI-a ga-mxal.6 (ADR A.5, K§2). Later lanes (sync, verify, tombstone, pull) build on
`NotesClient.request`; the signed upload PUT (A.4) deliberately does not go through it, because it
carries no Bearer.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from types import TracebackType
from typing import Any

import httpx

from arp_notes_cli.config import (
    AppConfig,
    ConfigError,
    add_app_argument,
    get_app,
    load_token,
)
from arp_notes_cli.registry import Subparsers

SUPPORTED_PROTOCOL_MAJOR = 1
MANIFEST_PAGE_LIMIT = 500  # A.2: limit <= 500


class ClientError(Exception):
    """The host could not be reached, refused the request, or answered something unusable."""

    def __init__(self, message: str, *, status: int | None = None, body: Any = None) -> None:
        super().__init__(message)
        self.status = status
        self.body = body


class ProtocolError(ClientError):
    """The host speaks a protocol major this CLI does not."""


def _major(protocol: Any) -> int | None:
    try:
        return int(str(protocol).split(".")[0])
    except ValueError:
        return None


def check_protocol(protocol: Any, *, where: str) -> None:
    major = _major(protocol)
    if major != SUPPORTED_PROTOCOL_MAJOR:
        raise ProtocolError(
            f"{where} reports protocol {protocol!r}; this CLI speaks protocol "
            f"{SUPPORTED_PROTOCOL_MAJOR}. Upgrade arp-notes (or the host)."
        )


def _error_detail(response: httpx.Response) -> tuple[str, Any]:
    try:
        body = response.json()
    except ValueError:
        return response.text.strip()[:300], None
    if isinstance(body, dict):
        for key in ("error", "detail", "message"):
            if body.get(key):
                return str(body[key]), body
    return json.dumps(body)[:300], body


class NotesClient:
    def __init__(self, app: AppConfig, token: str | None, *, timeout: float = 30.0) -> None:
        self.app = app
        self._token = token
        self._http = httpx.Client(timeout=timeout)

    def __enter__(self) -> NotesClient:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        self._http.close()

    def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any = None,
    ) -> Any:
        """Call `<url><api_prefix><path>` with the Bearer token; return the decoded JSON body."""
        if not self._token:
            raise ClientError(
                f"no API token for app {self.app.name!r}: run `arp-notes login --app "
                f"{self.app.name} --url {self.app.url}` or set ARP_NOTES_TOKEN"
            )
        url = self.app.api_base + path
        try:
            response = self._http.request(
                method,
                url,
                params={k: v for k, v in (params or {}).items() if v is not None},
                json=json,
                headers={"Authorization": f"Bearer {self._token}", "Accept": "application/json"},
            )
        except httpx.HTTPError as exc:
            raise ClientError(f"cannot reach {url}: {exc}") from exc
        if response.status_code >= 400:
            detail, body = _error_detail(response)
            hint = (
                " (token rejected: run `arp-notes login` again)"
                if response.status_code in (401, 403)
                else ""
            )
            raise ClientError(
                f"{method} {url} -> HTTP {response.status_code}: {detail}{hint}",
                status=response.status_code,
                body=body,
            )
        try:
            return response.json()
        except ValueError as exc:
            raise ClientError(f"{method} {url} returned a non-JSON body") from exc

    def capabilities(self) -> dict[str, Any]:
        """GET /notes/capabilities. Refuses a host whose protocol major is not 1."""
        caps = self.request("GET", "/notes/capabilities")
        if not isinstance(caps, dict) or "protocol" not in caps:
            raise ClientError(f"{self.app.api_base}/notes/capabilities is not an arp-notes answer")
        check_protocol(caps["protocol"], where=f"{self.app.name} capabilities")
        return caps

    def manifest(self, source_system: str, source_workspace: str) -> list[dict[str, Any]]:
        """Every ManifestRow for one (source_system, source_workspace), following `next_after`."""
        rows: list[dict[str, Any]] = []
        after: str | None = None
        while True:
            page = self.request(
                "GET",
                "/notes/sync/manifest",
                params={
                    "source_system": source_system,
                    "source_workspace": source_workspace,
                    "limit": MANIFEST_PAGE_LIMIT,
                    "after": after,
                },
            )
            if not isinstance(page, dict) or not isinstance(page.get("items"), list):
                raise ClientError("manifest response has no `items` list")
            if "protocol" in page:
                check_protocol(page["protocol"], where=f"{self.app.name} manifest")
            rows.extend(page["items"])
            next_after = page.get("next_after")
            if not next_after:
                return rows
            if next_after == after:
                raise ClientError("manifest paging does not advance (next_after repeats)")
            after = next_after

    def sync_sources(self) -> list[dict[str, Any]]:
        """K§2: `sync_sources` from GET /notes (one row per source system and workspace)."""
        listing = self.request("GET", "/notes", params={"limit": 1})
        sources = listing.get("sync_sources") if isinstance(listing, dict) else None
        if not isinstance(sources, list):
            raise ClientError("this host does not report sync_sources; pass --workspace")
        return sources


def open_client(app_name: str) -> NotesClient:
    return NotesClient(get_app(app_name), load_token(app_name))


def run_command(name: str, body: Callable[[], int]) -> int:
    """Run a command body, turning configuration and client errors into one stderr line.

    Exit codes: 0 ok, 1 a runtime failure (network, HTTP, protocol), 2 bad input or configuration.
    """
    try:
        return body()
    except ConfigError as exc:
        print(f"arp-notes {name}: {exc}", file=sys.stderr)
        return 2
    except ClientError as exc:
        print(f"arp-notes {name}: {exc}", file=sys.stderr)
        return 1


def _cmd_capabilities(args: argparse.Namespace) -> int:
    def body() -> int:
        with open_client(args.app) as client:
            caps = client.capabilities()
        print(json.dumps(caps, indent=2, ensure_ascii=False))
        return 0

    return run_command("capabilities", body)


def register(subparsers: Subparsers) -> None:
    parser = subparsers.add_parser(
        "capabilities",
        help="Print the host's GET /notes/capabilities answer.",
        description="Print what this host supports, so a driving LLM knows before it syncs.",
    )
    add_app_argument(parser)
    parser.set_defaults(func=_cmd_capabilities)
