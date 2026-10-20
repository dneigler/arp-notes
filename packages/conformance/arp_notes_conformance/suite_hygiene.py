"""Conformance: hygiene (K§6, R§4).

Owner: C7b ga-mxal.38. Hygiene is what lets a client LLM tidy a user's notes without surprising
them, so the checks hold the protocol to its safety rules rather than to a particular detector:

- the block comes only when asked for (`include_hygiene=true`), is shaped and capped as K§6.1
  says, and is absent altogether on a host that declares `hygiene=false`;
- a dismissed issue disappears from every scope; `resolve_tombstone` keeps or deletes only a note
  whose source was deleted;
- `apply_fix` and `merge_entities` never write without a `confirm_token` from a dry run of the
  same plan: no token is a dry run (or a refusal), a forged token is refused, an unknown issue is
  404. The kit never applies a real fix on a live host, so it follows a dry run only as far as
  its plan and token.

The issue the kit can raise on any host is `tombstoned_note` (sync a note, tombstone it). A
dismissal cannot be undone over the wire, so a run leaves a few `hygiene_dismissals` rows keyed to
notes it has deleted; they hide nothing a user could see. `merge_entities` needs two real
entities of the host: with only the fixture's `link_target` the kit sends a dry run for a pair
that cannot exist, and reports the check as skipped when the host answers 501 `not_supported` or
refuses the pair.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .harness import REJECTED, UNKNOWN_ID, CheckFailed, CheckSkipped, Harness
from .suite_core import link_target, need, same

Check = Callable[[Harness], None]
CHECKS: list[tuple[str, Check]] = []

SEVERITY = {"action": 0, "warn": 1, "info": 2}


def check(name: str) -> Callable[[Check], Check]:
    def register(fn: Check) -> Check:
        CHECKS.append((name, fn))
        return fn

    return register


def hygiene_on(h: Harness) -> None:
    if not h.capabilities["hygiene"]:
        raise CheckSkipped("the host declares hygiene=false (see hygiene.block_only_when_asked)")


def block(h: Harness, scope: str) -> dict[str, Any]:
    return h.call("GET", "/notes/hygiene", shape="HygieneBlock", params={"scope": scope})


def tombstoned(h: Harness, label: str) -> tuple[int, str]:
    """Sync a note, then tombstone it at its source. -> (note id, the issue key K§6.1 gives it)."""
    doc = h.fixture.doc("scratch")
    note_id, _ = h.upsert(
        doc, label=label, path=f"Scratch/{label}.md", body=f"{doc.body}\n{label}\n"
    )
    result = h.call(
        "POST",
        "/notes/sync/tombstone",
        shape="TombstoneResult",
        json={
            "source_system": h.fixture.source_system,
            "source_workspace": h.workspace,
            "source_doc_ids": [h.doc_id(label)],
        },
    )
    same(result["tombstoned"], 1, "tombstone result")
    return note_id, f"tombstoned_note:note:{note_id}"


def issue(found: dict[str, Any], key: str) -> dict[str, Any] | None:
    return next((i for i in found["issues"] if i["key"] == key), None)


def not_applied(h: Harness, response: Any, what: str) -> None:
    """A response that must never say a write happened."""
    if response.headers.get("content-type", "").startswith("application/json"):
        body = h.decode(response, what)
        need(
            not (isinstance(body, dict) and body.get("applied")),
            f"{what} applied a change without a valid confirm_token: {response.text[:200]}",
        )


# -- the block ------------------------------------------------------------------------------


@check("hygiene.block_only_when_asked")
def block_only_when_asked(h: Harness) -> None:
    note = h.create_note("Hygiene")
    asked = {"include_hygiene": "true"}
    if not h.capabilities["hygiene"]:
        got = h.call("GET", f"/notes/{note['id']}", shape="Note", params=asked)
        need(
            "hygiene" not in got,
            "hygiene=false but GET /notes/{id}?include_hygiene=true has a block",
        )
        raise CheckSkipped("the host declares hygiene=false: no block, and none was sent")

    for path, params in (
        ("/notes", {"q": h.tag, "limit": 5}),
        (f"/notes/{note['id']}", {}),
    ):
        plain = h.send("GET", path, params=params)
        h.expect_status(plain, 200, f"GET {path}")
        need("hygiene" not in h.decode(plain, path), f"GET {path} carries a hygiene block unasked")
        got = h.send("GET", path, params={**params, **asked})
        h.expect_status(got, 200, f"GET {path}?include_hygiene=true")
        body = h.decode(got, path)
        need("hygiene" in body, f"GET {path}?include_hygiene=true has no `hygiene` block (K§6.2)")
        h.schemas.validate("HygieneBlock", body["hygiene"], f"GET {path} hygiene")

    proposed = h.call("POST", f"/notes/{note['id']}/propose", shape="Proposal", params=asked)
    need("hygiene" in proposed, "POST /propose?include_hygiene=true has no `hygiene` block")
    upserted = h.call(
        "POST",
        "/notes/sync/upsert",
        shape="UpsertResult",
        params=asked,
        json=h.upsert_body(h.fixture.doc("scratch"), label="hygiene"),
    )
    h.track(upserted["note_id"])
    need(
        "hygiene" in upserted, "POST /notes/sync/upsert?include_hygiene=true has no `hygiene` block"
    )


@check("hygiene.block_shape_and_scopes")
def block_shape_and_scopes(h: Harness) -> None:
    hygiene_on(h)
    note = h.create_note("Scoped")
    for scope in ("all", f"note:{note['id']}"):
        found = block(h, scope)
        need(len(found["issues"]) <= 10, f"scope {scope}: a block holds at most 10 issues (K§6.1)")
        need(found["total"] >= len(found["issues"]), f"scope {scope}: total < issues shown")
        same(
            found["truncated"],
            found["total"] > len(found["issues"]),
            f"scope {scope}: truncated against total",
        )
        ranks = [SEVERITY[i["severity"]] for i in found["issues"]]
        same(ranks, sorted(ranks), f"scope {scope}: issues most severe first")
        for item in found["issues"]:
            kind, _, rest = item["key"].partition(":")
            need(
                kind == item["kind"] and rest.count(":") >= 1,
                f"issue key {item['key']!r} is not <kind>:<entity_type>:<ids> (K§6.1)",
            )
            for fix in item["fixes"]:
                need(
                    isinstance(fix["arguments"], dict) and fix["tool"],
                    f"issue {item['key']}: a fix needs a tool and its arguments",
                )
    h.fails("GET", "/notes/hygiene", REJECTED, params={"scope": "everything"})
    h.fails("GET", "/notes/hygiene", 404, "not_found", params={"scope": f"note:{UNKNOWN_ID}"})


# -- dismiss and resolve_tombstone ----------------------------------------------------------


@check("hygiene.dismiss_hides_the_issue")
def dismiss_hides_the_issue(h: Harness) -> None:
    hygiene_on(h)
    note_id, key = tombstoned(h, "dismissed")
    scope = f"note:{note_id}"
    found = issue(block(h, scope), key)
    need(found is not None, f"a tombstoned note raises no `{key}` issue in scope {scope}")
    assert found is not None
    same(found["kind"], "tombstoned_note", "issue kind")
    same(found["detected_by"], "core", "issue detected_by")
    need(
        any(s["entity_type"] == "note" and s["entity_id"] == note_id for s in found["subjects"]),
        "the issue's subjects do not name the tombstoned note",
    )
    tools = {(f["tool"], f["arguments"].get("action")) for f in found["fixes"]}
    need(
        {("resolve_tombstone", "keep"), ("resolve_tombstone", "delete")} <= tools,
        f"a tombstoned_note issue offers keep and delete through resolve_tombstone, got {tools}",
    )
    need(bool(found["title"]) and bool(found["explanation"]), "title and explanation are required")

    h.call(
        "POST",
        "/hygiene/dismiss",
        shape="DismissResult",
        json={"issue_key": key, "reason": "the kit says so"},
    )
    need(issue(block(h, scope), key) is None, "a dismissed issue is still in its note scope")
    need(issue(block(h, "all"), key) is None, "a dismissed issue is still in scope all")
    h.call("POST", "/hygiene/dismiss", shape="DismissResult", json={"issue_key": key})  # idempotent
    h.fails("POST", "/hygiene/dismiss", REJECTED, json={"issue_key": "no-such-kind"})
    h.fails("POST", "/hygiene/dismiss", REJECTED, json={})


@check("hygiene.resolve_tombstone")
def resolve_tombstone(h: Harness) -> None:
    hygiene_on(h)
    kept_id, kept_key = tombstoned(h, "kept")
    dropped_id, _ = tombstoned(h, "dropped")
    live = h.create_note("Live")

    kept = h.call(
        "POST",
        f"/notes/{kept_id}/resolve-tombstone",
        shape="ResolveTombstoneResult",
        json={"action": "keep"},
    )
    same((kept["note_id"], kept["action"]), (kept_id, "keep"), "resolve_tombstone keep")
    need(issue(block(h, f"note:{kept_id}"), kept_key) is None, "keep leaves the issue open")
    still = h.get_note(kept_id)
    need(still["deleted_at"] is not None, "keep must leave the note tombstoned (hidden)")
    need(
        all(i["id"] != kept_id for i in h.list_notes(q=h.tag, origin="source", limit=100)["items"]),
        "a kept tombstoned note must stay out of the default list",
    )

    gone = h.call(
        "POST",
        f"/notes/{dropped_id}/resolve-tombstone",
        shape="ResolveTombstoneResult",
        json={"action": "delete"},
    )
    same((gone["note_id"], gone["action"]), (dropped_id, "delete"), "resolve_tombstone delete")
    h.fails("GET", f"/notes/{dropped_id}", 404, "not_found")

    h.fails(
        "POST",
        f"/notes/{live['id']}/resolve-tombstone",
        409,
        "not_tombstoned",
        json={"action": "delete"},
    )
    same(h.get_note(live["id"])["id"], live["id"], "a live note survives resolve_tombstone delete")
    h.fails(
        "POST", f"/notes/{UNKNOWN_ID}/resolve-tombstone", 404, "not_found", json={"action": "keep"}
    )
    h.fails("POST", f"/notes/{kept_id}/resolve-tombstone", REJECTED, json={"action": "shred"})


# -- apply_fix and merge_entities -----------------------------------------------------------


@check("hygiene.apply_fix_requires_a_dry_run_token")
def apply_fix_requires_a_dry_run_token(h: Harness) -> None:
    hygiene_on(h)
    note_id, key = tombstoned(h, "fixme")
    found = issue(block(h, f"note:{note_id}"), key)
    need(found is not None, f"no `{key}` issue to try the fixes of")
    assert found is not None

    for index, fix in enumerate(found["fixes"]):
        asked = {"issue_key": key, "fix_index": index}
        bare = h.send("POST", "/hygiene/apply-fix", json=asked)
        not_applied(h, bare, f"apply_fix of fix {index} without a token")
        if bare.status_code == 200:  # it planned: the plan and the token are what must be right
            body = h.decode(bare, "POST /hygiene/apply-fix")
            h.schemas.validate("ApplyFixDryRun", body, "apply_fix dry run")
            same(body["dry_run"], True, "dry_run flag of a plan")
            need(bool(body["confirm_token"]), "a dry run must hand back a confirm_token")
        else:
            need(
                400 <= bare.status_code < 500,
                f"apply_fix without a token answered {bare.status_code}: {bare.text[:200]}",
            )
        forged = h.send(
            "POST", "/hygiene/apply-fix", json={**asked, "confirm_token": f"forged-{h.tag}"}
        )
        need(
            400 <= forged.status_code < 500,
            f"apply_fix with a forged confirm_token answered {forged.status_code}, not a 4xx",
        )
        not_applied(h, forged, f"apply_fix of fix {index} with a forged token")
        del fix  # the loop proves every fix the issue lists, whatever its tool

    h.fails(
        "POST",
        "/hygiene/apply-fix",
        404,
        json={"issue_key": f"tombstoned_note:note:{UNKNOWN_ID}", "fix_index": 0},
    )
    h.fails("POST", "/hygiene/apply-fix", REJECTED, json={"issue_key": key, "fix_index": -1})


@check("hygiene.merge_entities_dry_run")
def merge_entities_dry_run(h: Harness) -> None:
    hygiene_on(h)
    target = link_target(h)
    ghost = target.entity_id + 1_000_000_007  # an id of the same type that no host has
    ask = {
        "entity_type": target.entity_type,
        "keep_id": target.entity_id,
        "merge_ids": [ghost],
        "dry_run": True,
    }
    response = h.send("POST", "/hygiene/merge-entities", json=ask)
    if response.status_code == 501:
        error = h.decode(response, "POST /hygiene/merge-entities")
        h.schemas.validate("ErrorBody", error, "merge-entities refusal")
        same(error["error"], "not_supported", "error of a 501 merge-entities")
        raise CheckSkipped("the host does not merge entities (501 not_supported)")
    if response.status_code in (404, *REJECTED):
        raise CheckSkipped(
            f"the host merges {target.entity_type} entities but refused the kit's placeholder pair "
            f"({response.status_code}); the fixture would need a real mergeable pair"
        )
    h.expect_status(response, 200, "POST /hygiene/merge-entities (dry run)")
    body = h.decode(response, "POST /hygiene/merge-entities")
    h.schemas.validate("MergeEntitiesDryRun", body, "merge-entities dry run")
    need(bool(body["confirm_token"]), "a merge dry run must hand back a confirm_token")
    same(body["plan"]["reversible"], False, "plan.reversible (K§6.3: audited, not reversible)")

    unconfirmed = h.send("POST", "/hygiene/merge-entities", json={**ask, "dry_run": False})
    not_applied(h, unconfirmed, "merge_entities with dry_run=false and no token")
    forged = h.send(
        "POST",
        "/hygiene/merge-entities",
        json={**ask, "dry_run": False, "confirm_token": f"forged-{h.tag}"},
    )
    need(
        400 <= forged.status_code < 500,
        f"merge_entities with a forged confirm_token answered {forged.status_code}, not a 4xx",
    )
    not_applied(h, forged, "merge_entities with a forged token")
    if unconfirmed.status_code == 200:
        plan = h.decode(unconfirmed, "POST /hygiene/merge-entities")
        if "confirm_token" not in plan:
            raise CheckFailed("dry_run=false without a token must be a dry run (it has no token)")
