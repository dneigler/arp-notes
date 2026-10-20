# arp-notes-conformance

Black-box conformance kit (ADR §9.3): it drives any implementation over HTTP (A.2) and MCP (A.3),
so any stack can prove compliance. A host runs it in CI:

```python
from arp_notes_conformance import suite

suite(app=app, token=TOKEN)  # in-process ASGI
suite(base_url="https://...", token=TOKEN)  # any stack, over the wire
```

```sh
arp-notes-conformance --base-url https://notes.example.com --token $TOKEN
arp-notes verify --conformance --app pt        # the live-host gate, from the arp-notes CLI
```

## What it checks

Every check is named `<group>.<name>`; `--only <group>` or `only=[...]` runs a group.

| Group | Proves |
|---|---|
| `capabilities`, `notes`, `sync`, `review`, `entity` | the capabilities handshake, CRUD, manifest paging, upsert, rename, orphaning, tombstones, `review_pending`, by-entity (C7a) |
| `attachments` | upload-url → PUT 201; hash mismatch 409; replay 404; oversize 413; MIME 415; `attachments=false` refuses upload-url; signed content 200 / tampered 403 / expired 403 |
| `enrich` | propose shapes validate (empty is fine) and are cached; confirm creates links; a rejection and a confirmed link are never re-proposed; deferred items are what `review_pending` counts |
| `export` | export Markdown and manifest; the pull → sync round trip is `unchanged` with byte-equal bodies and the same sha256s; enrichment is opt-in |
| `mcp` | `tools/list` has the 13 notes tools (and the 4 hygiene tools when `capabilities.hygiene`); `notes_capabilities` equals REST; reads carry a hygiene block; write tools agree with REST |
| `hygiene` | the block only on request and capped; dismiss hides an issue; `resolve_tombstone`; `apply_fix` and `merge_entities` never write without a dry-run `confirm_token` |

A check that cannot say anything about a host is **skipped with its reason**, never passed: no
`link_target` in the fixture, `attachments=false`, no MCP endpoint, a host that does not merge
entities (501 `not_supported`).

The fixture's optional `merge_pair` (`{"entity_type", "keep_id", "merge_ids": [..]}`) names a real
mergeable pair of the host. With it `hygiene.merge_entities_dry_run` checks the host's real dry-run
plan (`keep`/`merge` are those ids), fails if the host refuses the pair, and runs the
missing-token and forged-token refusals against that plan. Without it the kit sends a placeholder
pair and skips when the host refuses it. The kit only ever asks for a dry run.

## MCP mode

The kit speaks JSON-RPC over Streamable HTTP itself and imports no MCP SDK. The endpoint is
`$ARP_NOTES_MCP_URL` (an absolute URL or a path on the host), else the first of `/mcp` and
`<api prefix>/mcp` that answers `initialize`. Without one the `mcp.*` checks are skipped.

## On a live host

A run works in its own `arpn-conformance-<id>` workspace and deletes the notes it made. Two things
cannot be undone over the wire: the (tiny) blobs it uploads, which a host's `unreferenced_blobs`
hygiene sweep collects after 30 days, and the hygiene dismissals for the notes it deleted.

**The two command lines treat the bundled fixture differently.** Its `link_target` (repertoire 10,
child movement 103) names the reference host's entities.

- `arp-notes verify --conformance` (and `arp-notes conformance`) leave `link_target`,
  `recognised_document` and `merge_pair` out, so the link checks are skipped with a reason.
- `arp-notes-conformance` (this package's own command) sends the bundled fixture as it is. Against
  any host but the reference one the link checks then fail rather than skip (`entity.include_children`
  is one). **Always pass `--fixture <dir>` there**, with a `fixture.json` written for the host (format:
  INTEGRATING.md, step 5), or the checks that need your entities will not mean anything.

`--fixture <dir>` works on both commands, and with it the link checks run.
