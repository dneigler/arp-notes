"""Conformance: HTTP harness (--base-url / --asgi), schema validation, fixtures.

Owner: C7a ga-mxal.14. The kit is black-box (ADR §9.3): it speaks only HTTP to a host, either a
live `base_url` or an ASGI app called in-process. Nothing here imports `arp_notes` except to find
the JSON Schemas, so a host in any language can be proven against the same checks.

A run writes only under its own `source_workspace` (`arpn-conformance-<run id>`) and deletes every
note it made when it finishes, so it is safe to point at a live deployment.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import uuid
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import jsonschema
from jsonschema.exceptions import best_match

DEFAULT_PREFIX = "/api/v1"
SCHEMAS_ENV = "ARP_NOTES_SCHEMAS"
# A malformed request is "a 4xx the host's framework chose": FastAPI answers 422, other stacks 400.
# A.2 pins 422 only where it says so (a bad content_hash), and those checks ask for 422 itself.
REJECTED = (400, 422)
UNKNOWN_ID = 2_147_483_000  # a note id no host has handed out


class CheckFailed(AssertionError):
    """A check saw the host break the protocol. The message says what, where and what came back."""


class CheckSkipped(Exception):
    """A check cannot run against this host or fixture. The message says why."""


def sha256_hex(data: bytes | str) -> str:
    return hashlib.sha256(data.encode("utf-8") if isinstance(data, str) else data).hexdigest()


# -- schemas --------------------------------------------------------------------------------


def _stem(shape: str) -> str:
    """`NoteSummary` -> `note_summary`, the name of the shape's schema file."""
    return re.sub(r"(?<!^)(?=[A-Z])", "_", shape).lower()


def find_schemas_dir(explicit: str | os.PathLike[str] | None = None) -> Path:
    """The `arp_notes/schemas` directory: `explicit`, else $ARP_NOTES_SCHEMAS, else the installed
    `arp-notes-core`."""
    candidates: list[Path] = []
    if explicit is not None:
        candidates.append(Path(explicit))
    elif os.environ.get(SCHEMAS_ENV):
        candidates.append(Path(os.environ[SCHEMAS_ENV]))
    else:
        try:
            spec = importlib.util.find_spec("arp_notes.schemas")
        except ImportError:  # no arp_notes at all
            spec = None
        if spec is not None and spec.origin:
            candidates.append(Path(spec.origin).parent)
    for path in candidates:
        if (path / "capabilities.json").is_file():
            return path
    raise FileNotFoundError(
        "cannot find the arp-notes JSON Schemas: install arp-notes-core, or pass schemas_dir= "
        f"(--schemas) or set ${SCHEMAS_ENV} to a copy of packages/core/arp_notes/schemas"
    )


class Schemas:
    """Validates a decoded response body against `<shape>.json` (JSON Schema 2020-12)."""

    def __init__(self, directory: str | os.PathLike[str] | None = None) -> None:
        self.directory = find_schemas_dir(directory)
        self._validators: dict[str, jsonschema.Draft202012Validator] = {}

    def validator(self, shape: str) -> jsonschema.Draft202012Validator:
        if shape not in self._validators:
            path = self.directory / f"{_stem(shape)}.json"
            if not path.is_file():
                raise FileNotFoundError(f"no schema for shape {shape!r}: {path}")
            self._validators[shape] = jsonschema.Draft202012Validator(
                json.loads(path.read_text("utf-8"))
            )
        return self._validators[shape]

    def validate(self, shape: str, body: Any, where: str = "response") -> None:
        error = best_match(self.validator(shape).iter_errors(body))
        if error is not None:
            at = "/".join(str(p) for p in error.absolute_path) or "(root)"
            raise CheckFailed(f"{where} is not a valid {shape}: at {at}: {error.message}")


# -- fixture --------------------------------------------------------------------------------


@dataclass(frozen=True)
class Document:
    """One note of the synthetic vault, as a client would sync it."""

    key: str
    path: str
    title: str
    body: str
    kind: str | None = None
    person: str | None = None
    note_date: str | None = None
    frontmatter: Mapping[str, Any] | None = None
    anchors: Mapping[str, str] = field(default_factory=dict)  # heading text -> anchor


@dataclass(frozen=True)
class LinkTarget:
    """An entity of the host under test that confirmed links can point at. `child` is one the
    host's link scheme reports as a child of it (K§2 include_children); leave it out if the host
    has none."""

    entity_type: str
    entity_id: int
    child: tuple[str, int] | None = None


@dataclass(frozen=True)
class Fixture:
    """The synthetic vault plus what the kit needs to know about the host's own entities.

    `link_target` is an entity that exists in the host. Without it the checks that need links
    are skipped. `recognised_document` names the document whose text the host's resolver turns
    into proposals (K§3: `review_pending > 0` after an upsert); without it that check is skipped.
    """

    source_system: str
    documents: Mapping[str, Document]
    link_target: LinkTarget | None = None
    recognised_document: str | None = None

    def doc(self, key: str) -> Document:
        if key not in self.documents:
            raise CheckSkipped(f"the fixture has no document {key!r}")
        return self.documents[key]


class _Default:
    def __repr__(self) -> str:
        return "DEFAULT"


DEFAULT = _Default()  # the bundled fixture: targets the C3 reference host's toy link scheme


def fixtures_dir() -> Path:
    """Where the bundled fixtures live: inside the wheel, else next to the package in a checkout."""
    packaged = Path(__file__).resolve().parent / "fixtures"
    return packaged if packaged.is_dir() else Path(__file__).resolve().parents[1] / "fixtures"


def load_fixture(source: Fixture | _Default | str | os.PathLike[str] | None = None) -> Fixture:
    """A `Fixture` from itself, from `DEFAULT`/None, or from a directory or JSON file written like
    the bundled `fixture.json` (document `file`s are relative to that file)."""
    if isinstance(source, Fixture):
        return source
    if source is None or isinstance(source, _Default):
        path = fixtures_dir() / "fixture.json"
    else:
        path = Path(source)
    if path.is_dir():
        path = path / "fixture.json"
    raw = json.loads(path.read_text("utf-8"))
    documents = {
        key: Document(
            key=key,
            path=spec["path"],
            title=spec["title"],
            # read as bytes, never through text mode, so line endings reach the host as written
            body=(path.parent / spec["file"]).read_bytes().decode("utf-8"),
            kind=spec.get("kind"),
            person=spec.get("person"),
            note_date=spec.get("note_date"),
            frontmatter=spec.get("frontmatter"),
            anchors=spec.get("anchors", {}),
        )
        for key, spec in raw["documents"].items()
    }
    target = raw.get("link_target")
    child = target.get("child") if target else None
    return Fixture(
        source_system=raw["source_system"],
        documents=documents,
        link_target=None
        if not target
        else LinkTarget(
            target["entity_type"],
            int(target["entity_id"]),
            None if not child else (child["entity_type"], int(child["entity_id"])),
        ),
        recognised_document=raw.get("recognised_document"),
    )


# -- connection -----------------------------------------------------------------------------


@contextmanager
def connect(
    *, app: Any = None, base_url: str | None = None, timeout: float = 30.0
) -> Iterator[httpx.Client]:
    """An `httpx.Client` on a live `base_url`, or on an ASGI `app` called in-process.

    ASGI mode runs the app's lifespan, and a server-side exception comes back as a 500 response
    (as it would over the wire), so a broken host fails a check instead of the whole run.
    """
    if (app is None) == (base_url is None):
        raise ValueError("pass exactly one of app= (ASGI) or base_url=")
    if app is not None:
        try:
            from starlette.testclient import TestClient
        except ImportError as exc:  # pragma: no cover - starlette ships with every FastAPI host
            raise RuntimeError("ASGI mode needs starlette: pip install starlette httpx") from exc
        with TestClient(app, base_url="http://testserver", raise_server_exceptions=False) as c:
            yield c
    else:
        assert base_url is not None
        with httpx.Client(base_url=base_url.rstrip("/"), timeout=timeout) as client:
            yield client


# -- harness --------------------------------------------------------------------------------


class Harness:
    """What every check gets: a client bound to one token, the schemas and the fixture."""

    def __init__(
        self,
        client: httpx.Client,
        *,
        token: str,
        fixture: Fixture,
        schemas: Schemas,
        prefix: str = DEFAULT_PREFIX,
        run_id: str | None = None,
    ) -> None:
        self.client = client
        self.token = token
        self.fixture = fixture
        self.schemas = schemas
        self.prefix = "/" + prefix.strip("/") if prefix.strip("/") else ""
        self.run_id = run_id or uuid.uuid4().hex[:10]
        self.created: list[int] = []
        self._checks_begun = 0
        self.begin()
        self._capabilities: dict[str, Any] | None = None

    def begin(self) -> None:
        """Start a check: a fresh `tag` and `workspace`, so one check's notes never show up in
        another's lists, manifests or by-entity results."""
        self._checks_begun += 1
        self.tag = f"{self.run_id}x{self._checks_begun}"  # one token, safe in any `q` search
        self.workspace = f"arpn-conformance-{self.tag}"

    # -- requests

    def send(
        self,
        method: str,
        path: str,
        *,
        json: Any = None,
        params: Mapping[str, Any] | None = None,
        auth: bool = True,
        token: str | None = None,
    ) -> httpx.Response:
        headers = {"Authorization": f"Bearer {token or self.token}"} if auth else {}
        return self.client.request(
            method, self.prefix + path, json=json, params=params, headers=headers
        )

    def call(
        self,
        method: str,
        path: str,
        *,
        shape: str | None = None,
        status: int = 200,
        json: Any = None,
        params: Mapping[str, Any] | None = None,
    ) -> Any:
        """Send, require `status`, validate the JSON body against `shape`, return the body."""
        response = self.send(method, path, json=json, params=params)
        where = f"{method} {path}"
        self.expect_status(response, status, where)
        if status == 204:
            if response.content:
                raise CheckFailed(f"{where}: 204 must have no body, got {response.text[:200]!r}")
            return None
        body = self.decode(response, where)
        if shape is not None:
            self.schemas.validate(shape, body, f"{where} response")
        return body

    def fails(
        self,
        method: str,
        path: str,
        status: int | tuple[int, ...],
        error: str | None = None,
        *,
        json: Any = None,
        params: Mapping[str, Any] | None = None,
    ) -> Any:
        """Send, require an error `status` (one of several allowed) and, if given, `error`."""
        response = self.send(method, path, json=json, params=params)
        where = f"{method} {path}"
        allowed = (status,) if isinstance(status, int) else status
        if response.status_code not in allowed:
            raise CheckFailed(
                f"{where}: expected status {' or '.join(map(str, allowed))}, got "
                f"{response.status_code}: {response.text[:300]}"
            )
        if error is None:
            return None
        body = self.decode(response, where)
        self.schemas.validate("ErrorBody", body, f"{where} error body")
        if body.get("error") != error:
            raise CheckFailed(f"{where}: expected error {error!r}, got {body.get('error')!r}")
        return body

    @staticmethod
    def expect_status(response: httpx.Response, status: int, where: str) -> None:
        if response.status_code != status:
            raise CheckFailed(
                f"{where}: expected status {status}, got {response.status_code}: "
                f"{response.text[:300]}"
            )

    @staticmethod
    def decode(response: httpx.Response, where: str) -> Any:
        try:
            return response.json()
        except ValueError as exc:
            raise CheckFailed(f"{where}: body is not JSON: {response.text[:200]!r}") from exc

    # -- host facts

    @property
    def capabilities(self) -> dict[str, Any]:
        caps = self._capabilities
        if caps is None:
            caps = self._capabilities = self.call(
                "GET", "/notes/capabilities", shape="Capabilities", status=200
            )
        return caps

    @property
    def kind(self) -> str:
        """A kind the host says it accepts."""
        kinds = self.capabilities["kinds"]
        return "note" if "note" in kinds or not kinds else kinds[0]

    # -- notes the run makes (all cleaned up by `cleanup`)

    def doc_id(self, label: str) -> str:
        return f"{self.tag}-{label}"

    def title(self, doc: Document) -> str:
        """The title `doc` syncs under: its own plus this check's tag, so `q=<tag>` finds it."""
        return f"{doc.title} {self.tag}"

    def track(self, note_id: int) -> int:
        if note_id not in self.created:
            self.created.append(note_id)
        return note_id

    def create_note(self, label: str, **fields: Any) -> dict[str, Any]:
        """POST /notes (an app note) titled `<label> <tag>`; returns the Note."""
        body = {"title": f"{label} {self.tag}", "kind": self.kind, **fields}
        note = self.call("POST", "/notes", shape="Note", status=201, json=body)
        self.track(note["id"])
        return note

    def upsert_body(
        self,
        doc: Document,
        *,
        label: str | None = None,
        body: str | None = None,
        path: str | None = None,
        **over: Any,
    ) -> dict[str, Any]:
        """A NoteUpsert for `doc` in this run's workspace; `label` makes its source_doc_id."""
        text = doc.body if body is None else body
        payload: dict[str, Any] = {
            "source_system": self.fixture.source_system,
            "source_workspace": self.workspace,
            "source_doc_id": self.doc_id(label or doc.key),
            "source_path": path or doc.path,
            "title": self.title(doc),
            "body_md": text,
            "content_hash": sha256_hex(text),
            "attachments": [],
        }
        for name in ("kind", "person", "note_date", "frontmatter"):
            value = getattr(doc, name)
            if value is not None:
                payload[name] = value
        payload.update(over)
        return payload

    def upsert(self, doc: Document, **kw: Any) -> tuple[int, dict[str, Any]]:
        """POST /notes/sync/upsert -> (note_id, UpsertResult)."""
        result = self.call(
            "POST",
            "/notes/sync/upsert",
            shape="UpsertResult",
            json=self.upsert_body(doc, **kw),
        )
        return self.track(result["note_id"]), result

    def get_note(self, note_id: int) -> dict[str, Any]:
        return self.call("GET", f"/notes/{note_id}", shape="Note")

    def list_notes(self, **params: Any) -> dict[str, Any]:
        return self.call("GET", "/notes", shape="NoteList", params=params)

    def confirm(self, note_id: int, *links: dict[str, Any]) -> dict[str, Any]:
        """POST /notes/{id}/confirm with only `links`."""
        body = {"links": list(links), "rejected": [], "action_items": []}
        return self.call("POST", f"/notes/{note_id}/confirm", shape="ConfirmResult", json=body)

    def cleanup(self) -> list[str]:
        """Delete every note this run made. Returns a warning per note that would not go."""
        warnings: list[str] = []
        for note_id in reversed(self.created):
            response = self.send("DELETE", f"/notes/{note_id}")
            if response.status_code not in (204, 404):
                warnings.append(
                    f"cleanup: DELETE /notes/{note_id} answered {response.status_code}: "
                    f"{response.text[:120]}"
                )
        self.created.clear()
        return warnings
