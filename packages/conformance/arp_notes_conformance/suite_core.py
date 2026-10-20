"""Conformance: capabilities, CRUD, sync manifest/upsert/rename/orphan/tombstone, review_pending.

Owner: C7a ga-mxal.14. Every check takes the `Harness`, drives the host over HTTP only, validates
each response against the JSON Schemas, and raises `CheckFailed` (or `CheckSkipped`, with the
reason) when it cannot say. `CHECKS` is the registry the runner reads; C7b's modules publish
theirs the same way.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .harness import (
    REJECTED,
    UNKNOWN_ID,
    CheckFailed,
    CheckSkipped,
    Document,
    Harness,
    LinkTarget,
    sha256_hex,
)

Check = Callable[[Harness], None]
CHECKS: list[tuple[str, Check]] = []


def check(name: str) -> Callable[[Check], Check]:
    def register(fn: Check) -> Check:
        CHECKS.append((name, fn))
        return fn

    return register


def need(condition: bool, message: str) -> None:
    if not condition:
        raise CheckFailed(message)


def same(actual: Any, expected: Any, what: str) -> None:
    if actual != expected:
        raise CheckFailed(f"{what}: expected {expected!r}, got {actual!r}")


def link_target(h: Harness) -> LinkTarget:
    if h.fixture.link_target is None:
        raise CheckSkipped("the fixture names no link_target entity of this host")
    return h.fixture.link_target


def anchored(h: Harness) -> tuple[Document, list[str]]:
    """The masterclass document and the anchors of its headings (at least two)."""
    doc = h.fixture.doc("masterclass")
    anchors = list(doc.anchors.values())
    if len(anchors) < 2:
        raise CheckSkipped("the masterclass document needs two anchored headings")
    return doc, anchors


# -- capabilities ---------------------------------------------------------------------------


@check("capabilities.shape")
def capabilities_shape(h: Harness) -> None:
    caps = h.call("GET", "/notes/capabilities", shape="Capabilities")
    same(caps["protocol"], 1, "capabilities.protocol")
    need(bool(caps["kinds"]), "capabilities.kinds is empty: a host must accept at least one kind")
    need(
        h.fixture.source_system in caps["source_systems"],
        f"capabilities.source_systems {caps['source_systems']} lacks "
        f"{h.fixture.source_system!r}, which the fixture syncs as",
    )
    for name, value in caps["limits"].items():
        need(value > 0, f"capabilities.limits.{name} must be positive, got {value}")
    for scheme in caps["schemes"]:
        need(bool(scheme["prefix"]), "capabilities.schemes[].prefix is empty")
    if caps["attachments"] is False:
        need(
            caps["mime_allowlist"] in (None, []),
            "attachments are off, so mime_allowlist should be null or empty",
        )


@check("capabilities.requires_auth")
def capabilities_requires_auth(h: Harness) -> None:
    for what, response in (
        ("no Authorization header", h.send("GET", "/notes/capabilities", auth=False)),
        ("a wrong token", h.send("GET", "/notes", token=f"not-a-token-{h.run_id}")),
    ):
        need(
            response.status_code in (401, 403),
            f"{what} must be refused with 401 or 403, got {response.status_code}",
        )


@check("capabilities.match_behaviour")
def capabilities_match_behaviour(h: Harness) -> None:
    caps = h.capabilities
    for kind in caps["kinds"][:8]:
        note = h.create_note("kind", kind=kind)
        same(note["kind"], kind, f"a note created with advertised kind {kind!r}")
    note = h.create_note("capabilities")
    if not caps["llm_enrich"]:
        h.fails("POST", f"/notes/{note['id']}/propose", 503, "llm_disabled", params={"llm": "true"})
    if not caps["someday"]:
        body = {"links": [], "rejected": [], "action_items": [], "someday": [{"mention": "x"}]}
        h.fails("POST", f"/notes/{note['id']}/confirm", 422, "someday_unsupported", json=body)


# -- notes CRUD -----------------------------------------------------------------------------


@check("notes.crud")
def notes_crud(h: Harness) -> None:
    body = {
        "title": f"Crud {h.tag}",
        "kind": h.kind,
        "body_md": "# Crud\n\nFirst draft.\n",
        "person": "Roy Example",
        "note_date": "2026-10-19",
        "place": "Studio B",
    }
    note = h.call("POST", "/notes", shape="Note", status=201, json=body)
    h.track(note["id"])
    for name, value in body.items():
        same(note[name], value, f"POST /notes echo of {name}")
    same(note["origin"], "app", "origin of a note made through POST /notes")
    same(note["version"], 1, "version of a new note")
    same((note["links"], note["attachments"], note["deleted_at"]), ([], [], None), "new note")

    same(h.get_note(note["id"])["body_md"], body["body_md"], "GET /notes/{id} body_md")

    patched = h.call(
        "PATCH",
        f"/notes/{note['id']}",
        shape="Note",
        json={"title": f"Crud {h.tag} v2", "body_md": "Second draft.\n", "person": "Ann Other"},
    )
    same(
        (patched["title"], patched["body_md"], patched["person"], patched["place"]),
        (f"Crud {h.tag} v2", "Second draft.\n", "Ann Other", "Studio B"),
        "PATCH /notes/{id} (omitted fields stay as they were)",
    )

    h.fails("POST", "/notes", REJECTED, json={"body_md": "no title"})
    h.fails("GET", f"/notes/{UNKNOWN_ID}", 404, "not_found")
    h.fails("PATCH", f"/notes/{UNKNOWN_ID}", 404, "not_found", json={"title": "x"})

    h.call("DELETE", f"/notes/{note['id']}", status=204)
    h.fails("GET", f"/notes/{note['id']}", 404, "not_found")
    h.fails("DELETE", f"/notes/{note['id']}", 404, "not_found")


@check("notes.list_filters_and_paging")
def notes_list_filters_and_paging(h: Harness) -> None:
    kinds = h.capabilities["kinds"]
    other_kind = kinds[1] if len(kinds) > 1 else kinds[0]
    made = {
        day: h.create_note(f"Listed {day}", kind=kind, note_date=f"2026-10-0{day}")
        for day, kind in ((1, h.kind), (2, other_kind), (3, h.kind))
    }
    ids = {n["id"] for n in made.values()}
    mine = {"q": h.tag, "origin": "app", "limit": 100}

    page = h.list_notes(**mine)
    same({i["id"] for i in page["items"]}, ids, "GET /notes?q=<run id>&origin=app")
    need(all(i["origin"] == "app" for i in page["items"]), "origin=app returned a source note")
    need(isinstance(page["sync_sources"], list), "GET /notes must carry sync_sources")

    seen: list[int] = []
    cursor: str | None = None
    for _ in range(5):
        params = {**mine, "limit": 2, **({"before": cursor} if cursor else {})}
        page = h.list_notes(**params)
        need(len(page["items"]) <= 2, f"limit=2 returned {len(page['items'])} items")
        seen += [i["id"] for i in page["items"]]
        cursor = page.get("next_cursor")
        if not cursor:
            break
    else:
        raise CheckFailed("paging with limit=2 over 3 notes never ended")
    same(sorted(seen), sorted(ids), "ids across pages (each note exactly once)")

    if other_kind != h.kind:
        only = h.list_notes(**mine, kind=other_kind)
        same([i["id"] for i in only["items"]], [made[2]["id"]], f"kind={other_kind!r} filter")
    day = h.list_notes(**mine, date_from="2026-10-02", date_to="2026-10-02")
    same([i["id"] for i in day["items"]], [made[2]["id"]], "date_from=date_to=2026-10-02")

    for bad in (0, 101):
        h.fails("GET", "/notes", REJECTED, params={"limit": bad})


@check("notes.autosave_conflict")
def notes_autosave_conflict(h: Harness) -> None:
    note = h.create_note("Autosave", body_md="v1\n")
    result = h.call(
        "PATCH",
        f"/notes/{note['id']}/autosave",
        shape="AutosaveResult",
        json={"body_md": "v2\n", "version": note["version"]},
    )
    same(sorted(result), ["note"], "autosave success envelope keys")
    saved = result["note"]
    same(saved["body_md"], "v2\n", "autosaved body_md")
    need(saved["version"] > note["version"], "a saved autosave must advance the version")

    stale = h.call(
        "PATCH",
        f"/notes/{note['id']}/autosave",
        shape="AutosaveResult",
        json={"body_md": "lost\n", "version": note["version"]},
    )
    same(sorted(stale), ["conflict", "server_data", "server_version"], "conflict envelope keys")
    same(stale["conflict"], True, "conflict flag")
    same(stale["server_version"], saved["version"], "conflict server_version")
    same(stale["server_data"]["body_md"], "v2\n", "conflict server_data keeps the saved body")
    same(h.get_note(note["id"])["body_md"], "v2\n", "body after a conflicting autosave")


@check("notes.read_only_import")
def notes_read_only_import(h: Harness) -> None:
    doc = h.fixture.doc("scratch")
    note_id, _ = h.upsert(doc)
    for field, value in (("title", "Renamed"), ("body_md", "edited\n")):
        h.fails("PATCH", f"/notes/{note_id}", 409, "read_only_import", json={field: value})
    h.fails(
        "PATCH",
        f"/notes/{note_id}/autosave",
        409,
        "read_only_import",
        json={"body_md": "edited\n", "version": 1},
    )
    editable = {"kind": h.kind, "person": "Ann Other", "note_date": "2026-01-02", "place": "Hall"}
    patched = h.call("PATCH", f"/notes/{note_id}", shape="Note", json=editable)
    for name, value in editable.items():
        same(patched[name], value, f"PATCH of {name} on an imported note")
    same(
        (patched["title"], patched["body_md"]),
        (h.title(doc), doc.body),
        "title and body of an imported note after refused edits",
    )


# -- sync: manifest, upsert, rename, orphan, tombstone --------------------------------------


@check("sync.upsert_created_unchanged_updated")
def sync_upsert_states(h: Harness) -> None:
    doc = h.fixture.doc("masterclass")
    note_id, first = h.upsert(doc)
    same(first["outcome"], "created", "first upsert outcome")
    same((first["missing_attachments"], first["links_orphaned"]), ([], 0), "first upsert")

    note_id_2, again = h.upsert(doc)
    same((again["outcome"], note_id_2), ("unchanged", note_id), "re-upsert of identical bytes")

    edited = doc.body + "\nAn added line.\n"
    note_id_3, third = h.upsert(doc, body=edited)
    same((third["outcome"], note_id_3), ("updated", note_id), "upsert with a new hash")

    note = h.get_note(note_id)
    same(note["body_md"], edited, "body after the update")
    same(note["content_hash"], sha256_hex(edited), "content_hash echo")
    same(note["origin"], "source", "origin of a synced note")
    same(
        (note["source_system"], note["source_workspace"], note["source_doc_id"]),
        (h.fixture.source_system, h.workspace, h.doc_id(doc.key)),
        "source identity",
    )
    same(note["source_path"], doc.path, "source_path")
    need(note["last_synced_at"] is not None, "a synced note has last_synced_at")
    if doc.frontmatter is not None:
        same(note["frontmatter"], dict(doc.frontmatter), "frontmatter (kept exactly as sent)")

    listed = h.list_notes(source_system=h.fixture.source_system, origin="source", q=h.tag)
    row = next((i for i in listed["items"] if i["id"] == note_id), None)
    need(row is not None, "a synced note is listed under its source_system")
    assert row is not None
    same((row["source_workspace"], row["source_path"]), (h.workspace, doc.path), "list row")
    sources = [
        s
        for s in listed["sync_sources"]
        if (s["source_system"], s["source_workspace"]) == (h.fixture.source_system, h.workspace)
    ]
    need(len(sources) == 1 and sources[0]["note_count"] >= 1, "sync_sources lists this workspace")


@check("sync.upsert_keeps_every_byte")
def sync_upsert_keeps_every_byte(h: Harness) -> None:
    """The server stores source bodies verbatim: the editor spike's 33-construct corpus included."""
    for doc in h.fixture.documents.values():
        note_id, result = h.upsert(doc)
        same(result["outcome"], "created", f"upsert of {doc.key}")
        note = h.get_note(note_id)
        same(note["body_md"].encode("utf-8"), doc.body.encode("utf-8"), f"{doc.key} body bytes")
        same(note["content_hash"], sha256_hex(doc.body), f"{doc.key} content_hash")


@check("sync.upsert_rejects_a_bad_hash")
def sync_upsert_rejects_a_bad_hash(h: Harness) -> None:
    doc = h.fixture.doc("scratch")
    for bad in ("not-a-hash", sha256_hex(doc.body)[:63]):
        body = h.upsert_body(doc, label="badhash", content_hash=bad)
        h.fails("POST", "/notes/sync/upsert", 422, json=body)


@check("sync.manifest_paging")
def sync_manifest_paging(h: Harness) -> None:
    doc = h.fixture.doc("scratch")
    labels = ["m1", "m2", "m3"]
    for label in labels:
        h.upsert(doc, label=label, path=f"Scratch/{label}.md", body=f"{doc.body}\n{label}\n")
    where = {"source_system": h.fixture.source_system, "source_workspace": h.workspace}

    rows: list[dict[str, Any]] = []
    after: str | None = None
    pages = 0
    while True:
        params = {**where, "limit": 2, **({"after": after} if after else {})}
        page = h.call("GET", "/notes/sync/manifest", shape="ManifestPage", params=params)
        same(page["protocol"], 1, "manifest protocol")
        need(len(page["items"]) <= 2, f"limit=2 returned {len(page['items'])} rows")
        rows += page["items"]
        after = page.get("next_after")
        pages += 1
        if not after:
            break
        need(pages < 10, "manifest paging never ended")
    need(pages >= 2, "3 documents at limit=2 must take two pages")
    ids = [r["source_doc_id"] for r in rows]
    same(ids, sorted(h.doc_id(label) for label in labels), "manifest ids across pages, ascending")
    for row, label in zip(rows, labels, strict=True):
        expected = f"{doc.body}\n{label}\n"
        same(row["content_hash"], sha256_hex(expected), f"manifest content_hash of {label}")
        same(row["source_path"], f"Scratch/{label}.md", f"manifest source_path of {label}")
        same(row["attachments"], [], f"manifest attachments of {label}")

    empty = h.call(
        "GET",
        "/notes/sync/manifest",
        shape="ManifestPage",
        params={**where, "source_workspace": f"{h.workspace}-none"},
    )
    same((empty["items"], empty.get("next_after")), ([], None), "manifest of an unused workspace")
    h.fails(
        "GET", "/notes/sync/manifest", REJECTED, params={"source_system": where["source_system"]}
    )
    h.fails("GET", "/notes/sync/manifest", REJECTED, params={**where, "limit": 501})


@check("sync.rename_keeps_identity")
def sync_rename_keeps_identity(h: Harness) -> None:
    doc = h.fixture.doc("masterclass")
    note_id, _ = h.upsert(doc, path="Lessons/Before.md")
    moved_id, moved = h.upsert(doc, path="Archive/After.md")
    same(moved_id, note_id, "note id after a rename")
    need(moved["outcome"] in ("unchanged", "updated"), f"rename outcome {moved['outcome']!r}")
    same(h.get_note(note_id)["source_path"], "Archive/After.md", "source_path after a rename")

    edited = doc.body + "\nEdited while moving.\n"
    both_id, both = h.upsert(doc, path="Archive/Again.md", body=edited)
    same((both_id, both["outcome"]), (note_id, "updated"), "rename together with an edit")

    page = h.call(
        "GET",
        "/notes/sync/manifest",
        shape="ManifestPage",
        params={"source_system": h.fixture.source_system, "source_workspace": h.workspace},
    )
    same(
        [(r["source_doc_id"], r["source_path"]) for r in page["items"]],
        [(h.doc_id(doc.key), "Archive/Again.md")],
        "manifest after renames (one row, the new path)",
    )


@check("sync.heading_edit_orphans_only_that_anchor")
def sync_heading_edit_orphans_only_that_anchor(h: Harness) -> None:
    target = link_target(h)
    doc, (first, second, *_) = anchored(h)
    headings = {anchor: heading for heading, anchor in doc.anchors.items()}
    note_id, _ = h.upsert(doc)
    entity = {"entity_type": target.entity_type, "entity_id": target.entity_id}
    made = h.confirm(
        note_id,
        {**entity, "anchor": first, "quote": "first passage"},
        {**entity, "anchor": second, "quote": "second passage"},
        {**entity, "anchor": None, "quote": "whole note"},
    )
    same(made["links_created"], 3, "links confirmed")

    def statuses() -> dict[str | None, str]:
        return {link["anchor"]: link["status"] for link in h.get_note(note_id)["links"]}

    same(
        statuses(),
        {first: "confirmed", second: "confirmed", None: "confirmed"},
        "link statuses before the edit",
    )
    heading = f"## {headings[first]}"
    need(heading in doc.body, f"the fixture body has no {heading!r} line")
    edited = doc.body.replace(heading, f"{heading} (slowly)", 1)
    _, result = h.upsert(doc, body=edited)
    same((result["outcome"], result["links_orphaned"]), ("updated", 1), "upsert after the edit")
    same(
        statuses(),
        {first: "orphaned", second: "confirmed", None: "confirmed"},
        "link statuses after the heading edit (only that anchor orphans)",
    )


@check("sync.tombstone_hides_from_list")
def sync_tombstone_hides_from_list(h: Harness) -> None:
    doc = h.fixture.doc("scratch")
    gone_id, _ = h.upsert(doc, label="gone", path="Scratch/gone.md", body=f"{doc.body}\ngone\n")
    kept_id, _ = h.upsert(doc, label="kept", path="Scratch/kept.md", body=f"{doc.body}\nkept\n")
    where = {"source_system": h.fixture.source_system, "source_workspace": h.workspace}
    unknown = h.doc_id("never-synced")

    result = h.call(
        "POST",
        "/notes/sync/tombstone",
        shape="TombstoneResult",
        json={**where, "source_doc_ids": [h.doc_id("gone"), unknown]},
    )
    same((result["tombstoned"], result["unknown"]), (1, [unknown]), "tombstone result")

    mine = {"q": h.tag, "origin": "source", "limit": 100}
    same(
        [i["id"] for i in h.list_notes(**mine)["items"]], [kept_id], "GET /notes after a tombstone"
    )
    shown = h.list_notes(**mine, include_deleted="true")
    same({i["id"] for i in shown["items"]}, {gone_id, kept_id}, "GET /notes?include_deleted=true")
    row = next(i for i in shown["items"] if i["id"] == gone_id)
    need(row["deleted_at"] is not None, "a tombstoned note's summary carries deleted_at")

    note = h.get_note(gone_id)
    need(note["deleted_at"] is not None, "a tombstoned note stays readable, with deleted_at")
    same(note["body_md"], f"{doc.body}\ngone\n", "body of a tombstoned note (retained)")

    page = h.call("GET", "/notes/sync/manifest", shape="ManifestPage", params=where)
    deleted = {r["source_doc_id"]: r["deleted_at"] for r in page["items"]}
    need(deleted.get(h.doc_id("gone")) is not None, "manifest row of a tombstone has deleted_at")
    same(deleted.get(h.doc_id("kept")), None, "manifest row of a live note")

    empty = h.call(
        "POST",
        "/notes/sync/tombstone",
        shape="TombstoneResult",
        json={**where, "source_doc_ids": []},
    )
    same((empty["tombstoned"], empty["unknown"]), (0, []), "tombstone of no ids")


@check("sync.tombstone_orphans_links")
def sync_tombstone_orphans_links(h: Harness) -> None:
    target = link_target(h)
    doc = h.fixture.doc("masterclass")
    note_id, _ = h.upsert(doc, label="linked")
    h.confirm(
        note_id,
        {"entity_type": target.entity_type, "entity_id": target.entity_id, "quote": "x"},
    )
    where = {"source_system": h.fixture.source_system, "source_workspace": h.workspace}
    h.call(
        "POST",
        "/notes/sync/tombstone",
        shape="TombstoneResult",
        json={**where, "source_doc_ids": [h.doc_id("linked")]},
    )
    note = h.get_note(note_id)
    same([link["status"] for link in note["links"]], ["orphaned"], "links of a tombstoned note")


# -- review_pending -------------------------------------------------------------------------


@check("review.pending_after_upsert")
def review_pending_after_upsert(h: Harness) -> None:
    mode = h.capabilities["propose_on_sync"]
    if h.fixture.recognised_document is None:
        raise CheckSkipped("the fixture names no recognised_document the host proposes from")
    doc = h.fixture.doc(h.fixture.recognised_document)
    note_id, _ = h.upsert(doc)
    note = h.get_note(note_id)
    rows = h.list_notes(q=h.tag, origin="source", limit=100)["items"]
    listed = next(i for i in rows if i["id"] == note_id)
    if mode == "off":
        same((note["review_pending"], listed["review_pending"]), (0, 0), "review_pending, sync off")
        return
    need(
        note["review_pending"] > 0,
        f"capabilities.propose_on_sync is {mode!r} but a synced note whose text the host "
        f"recognises has review_pending {note['review_pending']} after the upsert",
    )
    same(listed["review_pending"], note["review_pending"], "list row review_pending")

    h.upsert(doc)  # unchanged: nothing is re-proposed, nothing is lost
    same(h.get_note(note_id)["review_pending"], note["review_pending"], "after an unchanged upsert")

    where = {"source_system": h.fixture.source_system, "source_workspace": h.workspace}
    h.call(
        "POST",
        "/notes/sync/tombstone",
        shape="TombstoneResult",
        json={**where, "source_doc_ids": [h.doc_id(doc.key)]},
    )
    same(h.get_note(note_id)["review_pending"], 0, "review_pending of a tombstoned note (K§3.6)")


# -- by-entity ------------------------------------------------------------------------------


@check("entity.notes_by_entity")
def entity_notes_by_entity(h: Harness) -> None:
    target = link_target(h)
    doc, (anchor, *_) = anchored(h)
    note_id, _ = h.upsert(doc)
    h.confirm(
        note_id,
        {
            "entity_type": target.entity_type,
            "entity_id": target.entity_id,
            "anchor": anchor,
            "quote": "the passage",
        },
    )
    path = f"/notes/by-entity/{target.entity_type}/{target.entity_id}"
    found = h.call("GET", path, shape="EntityNotes", params={"limit": 100})
    item = next((i for i in found["items"] if i["note"]["id"] == note_id), None)
    need(item is not None, f"GET {path} does not list the note with a confirmed link")
    assert item is not None
    same(
        [(link["entity_type"], link["entity_id"], link["anchor"]) for link in item["links"]],
        [(target.entity_type, target.entity_id, anchor)],
        "links of the by-entity item",
    )
    same([link["status"] for link in item["links"]], ["confirmed"], "by-entity link status")
    need(
        len(h.call("GET", path, shape="EntityNotes", params={"limit": 1})["items"]) <= 1,
        "limit=1 returned more than one item",
    )


@check("entity.include_children")
def entity_include_children(h: Harness) -> None:
    target = link_target(h)
    if target.child is None:
        raise CheckSkipped("the fixture's link_target has no child entity")
    child_type, child_id = target.child
    doc, (anchor, *_) = anchored(h)
    note_id, _ = h.upsert(doc, label="children")
    h.confirm(
        note_id,
        {"entity_type": child_type, "entity_id": child_id, "anchor": anchor, "quote": "child"},
    )
    path = f"/notes/by-entity/{target.entity_type}/{target.entity_id}"

    plain = h.call("GET", path, shape="EntityNotes", params={"limit": 100})
    need(
        all(i["note"]["id"] != note_id for i in plain["items"]),
        "without include_children a note linked only to a child must not be listed",
    )
    deep = h.call(
        "GET", path, shape="EntityNotes", params={"limit": 100, "include_children": "true"}
    )
    item = next((i for i in deep["items"] if i["note"]["id"] == note_id), None)
    need(item is not None, "include_children=true must list the note linked to a child")
    assert item is not None
    via = [link.get("via") for link in item["links"]]
    same(
        via,
        [{"entity_type": child_type, "entity_id": child_id}],
        "via of a link that matched through a child",
    )
