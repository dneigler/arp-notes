# arp-notes wire protocol

```
protocol_version: 1
```

This is the wire contract between an arp-notes host (any stack) and its clients (the CLI, the UI
package, MCP clients). **PROTOCOL.md and the conformance kit are the product**; the Python and
React packages in this repository are reference implementations.

- Breaking wire changes bump the major version; additive changes are minor. Servers return
  `protocol` in `GET /notes/sync/manifest`, and the CLI refuses a major it does not speak.
- Part 1 is the base contract (appendix A of the design record). **Part 2 amends it and wins
  wherever the two differ.** References such as `K§3` point at sections of Part 2.
- This is the initial copy (C0). The REST section is brought to byte-match with the routers by
  the C3 lane; a change to anything here needs a contract bead first.

---

# Part 1 · Base contract (A.1–A.6)

## A.1 Migration `database/migrations/043_notes.sql` (hand-mirror into `database/schema_postgres.sql`)

```sql
-- Migration 043: Notes sync — notes, content-addressed blobs, note attachments, note links,
-- upload tickets (ADR gascity/docs/arpinator/notes-sync-adr.md, epic ga-mxal / PT epic in §7.1).
-- Additive and idempotent (every statement guards itself; the runner skips the whole file on error).
-- user_id is plain TEXT NOT NULL with no FK to users (house rule, see 041).

CREATE TABLE IF NOT EXISTS notes (
    id SERIAL PRIMARY KEY,
    user_id TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'note',          -- masterclass|workshop|lecture|reading|video|reflection|meeting|note (open vocabulary)
    title TEXT NOT NULL,
    body_md TEXT NOT NULL DEFAULT '',           -- verbatim for origin='source'
    frontmatter JSONB DEFAULT '{}',             -- parsed YAML as given; keys preserved as-is
    person TEXT,                                -- presenter / author (free text, D6)
    note_date TEXT,                             -- YYYY-MM-DD (house TEXT-date convention)
    place TEXT,
    origin TEXT NOT NULL DEFAULT 'app',         -- 'app' (editable) | 'source' (read-only import)
    source_system TEXT,                         -- 'obsidian'|'notion'|'apple_notes'|'llm'|NULL
    source_workspace TEXT,                      -- vault name | Notion workspace id | Mac store id
    source_doc_id TEXT,                         -- arp_id | Notion page id | ZIDENTIFIER | client uuid
    source_path TEXT,                           -- current path at last sync (display + deep link only)
    source_url TEXT,                            -- obsidian://open?vault=..&file=.. | https://notion.so/.. | NULL
    source_modified_at TEXT,                    -- ISO-8601 as reported by the source
    content_hash TEXT,                          -- sha256 hex of the verbatim source bytes
    last_synced_at TIMESTAMP,
    deleted_at TIMESTAMP NULL,                  -- tombstone (source deletion); body and links retained
    created_via TEXT DEFAULT 'web',             -- 'web'|'mobile'|'mcp'|'cli'|'chat'|'ai'
    version INTEGER DEFAULT 1,                  -- autosave optimistic concurrency (app notes only)
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_notes_source_identity
    ON notes(user_id, source_system, source_workspace, source_doc_id) WHERE source_doc_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_notes_user_date ON notes(user_id, note_date);
CREATE INDEX IF NOT EXISTS idx_notes_user_updated ON notes(user_id, updated_at);
CREATE INDEX IF NOT EXISTS idx_notes_user_live ON notes(user_id) WHERE deleted_at IS NULL;

CREATE TABLE IF NOT EXISTS blobs (                -- content-addressed, per user
    id SERIAL PRIMARY KEY,
    user_id TEXT NOT NULL,
    sha256 TEXT NOT NULL,                       -- 64 lowercase hex
    mime TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    storage_path TEXT NOT NULL,                 -- backend-specific locator via the Storage port (disk: path; Postgres backend: the sha256; S3: object key) — D16
    width INTEGER,
    height INTEGER,                             -- images only, best effort
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id, sha256)
);

CREATE TABLE IF NOT EXISTS note_attachments (
    id SERIAL PRIMARY KEY,
    note_id INTEGER NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
    blob_id INTEGER NOT NULL REFERENCES blobs(id) ON DELETE RESTRICT,
    filename TEXT NOT NULL,                     -- as named in the source
    ref_in_markdown TEXT NOT NULL,              -- exact embed/link text in body_md, e.g. '![[2026-10-18 Masterclass-1792329672740.webp]]'
    sort_order INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(note_id, ref_in_markdown)
);
CREATE INDEX IF NOT EXISTS idx_note_attachments_blob ON note_attachments(blob_id);

CREATE TABLE IF NOT EXISTS note_links (          -- app-owned enrichment, anchored
    id SERIAL PRIMARY KEY,
    note_id INTEGER NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
    user_id TEXT NOT NULL,
    entity_type TEXT NOT NULL,                  -- 'repertoire'|'movement'|'section'|'composer'|'technique'|'instructor'
    entity_id INTEGER NOT NULL,
    anchor TEXT,                                -- heading slug or '^block-id'; NULL = whole note
    quote TEXT,                                 -- excerpt the link was made from
    comment TEXT,                               -- takeaway (app-owned)
    action_item TEXT,
    action_completed INTEGER DEFAULT 0,
    action_completed_at TIMESTAMP,
    backlog_id INTEGER,                         -- practice_backlog.id created on confirm (no FK; backlog rows are user-deletable)
    status TEXT NOT NULL DEFAULT 'confirmed',   -- 'confirmed'|'rejected'|'orphaned'
    proposed_by TEXT,                           -- 'resolver'|'llm'|'user'
    confidence REAL,
    sort_order INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_note_links_entity ON note_links(entity_type, entity_id, status);
CREATE INDEX IF NOT EXISTS idx_note_links_note ON note_links(note_id, status);
CREATE UNIQUE INDEX IF NOT EXISTS idx_note_links_dedupe
    ON note_links(note_id, entity_type, entity_id, COALESCE(anchor, ''));

CREATE TABLE IF NOT EXISTS upload_tickets (       -- one-time PUT URLs (A.4)
    id SERIAL PRIMARY KEY,
    user_id TEXT NOT NULL,
    token_hash TEXT NOT NULL UNIQUE,            -- sha256 of the url token; token itself never stored
    sha256 TEXT NOT NULL,
    mime TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    filename TEXT,
    expires_at TIMESTAMP NOT NULL,
    consumed_at TIMESTAMP NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

ALTER TABLE practice_backlog ADD COLUMN IF NOT EXISTS source_note_link_id INTEGER;  -- source='note'
CREATE INDEX IF NOT EXISTS idx_practice_backlog_source_note ON practice_backlog(source_note_link_id);

-- PT adapter delta (D16, rev 2): attachment bytes in Postgres behind the Storage port.
-- Not part of the core DDL — other hosts choose their own Storage backend.
CREATE TABLE IF NOT EXISTS note_blobs (
    user_id TEXT NOT NULL,
    sha256 TEXT NOT NULL,                       -- matches blobs.sha256
    mime TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    bytes BYTEA NOT NULL,                       -- served by chunked reads only (D16)
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (user_id, sha256)
);
```

Constants frozen with it: `_STORY_TYPE_RANK["note_doc"] = 7` (appended; existing `"note"` = `repertoire_notes` is untouched); `practice_backlog.source` gains the value `'note'`; `activity_log.event_type` values `note_synced`, `note_created`, `note_enriched`, `note_tombstoned`.

## A.2 REST (`/api/v1`, Bearer via `require_user_id` unless marked PUBLIC). Pydantic in `schemas/pydantic/notes.py`.

**Shapes** (JSON; `?` = optional/nullable):
```
Note        {id, user_id, kind, title, body_md, frontmatter, person?, note_date?, place?, origin, source_system?, source_workspace?,
             source_doc_id?, source_path?, source_url?, source_modified_at?, content_hash?, last_synced_at?, deleted_at?,
             created_via, version, created_at, updated_at,
             attachments: [Attachment], links: [NoteLink]}               -- links/attachments included by GET /notes/{id}
NoteSummary {id, kind, title, person?, note_date?, origin, source_system?, last_synced_at?, deleted_at?, link_count, attachment_count, updated_at}
Attachment  {id, blob_id, filename, ref_in_markdown, mime, size_bytes, sha256, width?, height?, content_url}   -- content_url is signed, expires ≤1 h
NoteLink    {id, entity_type, entity_id, entity_label, entity_slug?, anchor?, quote?, comment?, action_item?, action_completed,
             backlog_id?, status, proposed_by?, confidence?, sort_order}
ManifestRow {source_doc_id, source_path, content_hash, attachments: [sha256], last_synced_at, deleted_at?}
NoteUpsert  {source_system, source_workspace, source_doc_id, source_path, title, body_md, frontmatter?, source_modified_at?,
             source_url?, content_hash, kind?, person?, note_date?, place?,
             attachments: [{sha256, filename, mime, size_bytes, ref_in_markdown}]}
UpsertResult{note_id, outcome: 'created'|'updated'|'unchanged', missing_attachments: [sha256], links_orphaned: int}
Proposal    {note_id, links: [ProposedLink], action_items: [ProposedAction], takeaways: [string],
             unresolved: [{mention, anchor?, quote, candidates: [{entity_type, entity_id, entity_label, confidence}]}],
             generated_by: ['resolver'] | ['resolver','llm']}
ProposedLink{entity_type, entity_id, entity_label, anchor?, quote, confidence, proposed_by, reason,
             candidates?: [{entity_type, entity_id, entity_label, confidence}]}   -- candidates present ⇒ ambiguous, user must pick
ProposedAction {text, anchor?, entity_type?, entity_id?, lane: 'practice'|'lesson', proposed_by}
ConfirmBody {links: [{entity_type, entity_id, anchor?, quote?, comment?, proposed_by?, confidence?}],
             rejected: [{entity_type, entity_id, anchor?}],
             action_items: [{text, anchor?, entity_type?, entity_id?, lane, link_index?}],   -- link_index → attach to links[i]
             takeaways?: [{anchor?, comment}]}
ConfirmResult {links_created, links_rejected, backlog_created: [int], takeaways_created}
```

**Endpoints**
```
GET    /notes/capabilities                                                                 → {protocol:1, attachments:bool, mime_allowlist:[..]|null, limits:{max_attachment_bytes, max_note_bytes, max_body_chars, ...},
                                                                                              kinds:[...], source_systems:[...], export:bool, llm_enrich:bool, schemes:[{prefix, entity_types}]}   (§9.2 Policy, self-describing; rev 2)
GET    /notes/{id}/export?with_enrichment=false&enrichment_style=frontmatter|companion     → text/markdown + X-Arp-Attachments manifest header (§3.7; 403 when policy export=off; rev 2)
GET    /notes?kind&origin&source_system&q&date_from&date_to&limit(1..100)&before(cursor)   → {items:[NoteSummary], next_cursor?}
POST   /notes                 {kind?, title, body_md?, person?, note_date?, place?}        → 201 Note   (origin='app', created_via from client)
GET    /notes/{id}                                                                        → Note       (404)
PATCH  /notes/{id}            {kind?, title?, body_md?, person?, note_date?, place?}      → Note       (409 {"error":"read_only_import"} for origin='source' except kind/person/note_date/place which are editable on both)
PATCH  /notes/{id}/autosave   {body_md, version}                                           → 200 {note} | 200 {conflict:true, server_version, server_data}   (house envelope; app notes only)
DELETE /notes/{id}                                                                        → 204
GET    /notes/by-entity/{entity_type}/{entity_id}?limit                                   → {items:[{note: NoteSummary, links:[NoteLink]}]}
GET    /notes/sync/manifest?source_system&source_workspace&limit(≤500)&after(source_doc_id) → {items:[ManifestRow], next_after?}
POST   /notes/sync/upsert     NoteUpsert                                                  → 200 UpsertResult   (422 bad hash format; 409 {"error":"blob_missing", missing:[sha256]} only when attachments reference sha256s that must exist first — see A.4 ordering)
POST   /notes/sync/tombstone  {source_system, source_workspace, source_doc_ids:[string]}  → {tombstoned: int, unknown: [string]}
POST   /notes/{id}/propose?llm=false                                                      → Proposal   (llm=true → 503 {"error":"llm_disabled"} unless NOTES_LLM_ENRICH=1)
POST   /notes/{id}/confirm    ConfirmBody                                                 → ConfirmResult
POST   /attachments/upload-url {sha256, mime, size_bytes, filename}                       → {status:'exists', blob_id} | {status:'upload', upload_url, method:'PUT', expires_at}   (413 over limit; 415 mime)
PUT    /attachments/upload/{token}   PUBLIC, raw body, Content-Type: <mime>, Content-Length   → 201 {blob_id, sha256} | 404 unknown/consumed/expired | 409 {"error":"hash_mismatch"} | 413
GET    /attachments/{blob_id}                                                             → Attachment (meta)
GET    /attachments/{blob_id}/content?exp=<unix>&sig=<hex>   PUBLIC                        → bytes (Content-Type, Cache-Control: private, max-age=3600) | 403 bad/expired sig
```

## A.3 MCP tools (13, rev 2; all three parity files; names frozen)

| Tool | R/W | Maps to | Input (JSON Schema summary) |
|---|---|---|---|
| `notes_capabilities` | R | `GET /notes/capabilities` | `{}` — self-describing capability policy (§9.2), **called by clients before syncing** (rev 2) |
| `list_notes` | R | `GET /notes` | `{kind?, origin?, source_system?, q?, date_from?, date_to?, limit?}` |
| `get_note` | R | `GET /notes/{id}` | `{note_id:int}` → Note (body truncated to 20 k chars with `truncated:true`) |
| `get_notes_for_entity` | R | `GET /notes/by-entity/…` | `{entity_type, entity_id, limit?}` |
| `create_note` | W | `POST /notes` | `{title, body_md?, kind?, person?, note_date?, place?, source_system:'llm'?, source_doc_id?}` — text only (D14) |
| `update_note` | W | `PATCH /notes/{id}` | `{note_id, title?, body_md?, kind?, person?, note_date?, place?}` |
| `delete_note` | W | `DELETE /notes/{id}` | `{note_id}` |
| `notes_sync_manifest` | R | `GET /notes/sync/manifest` | `{source_system, source_workspace, limit?, after?}` |
| `notes_sync_upsert` | W | `POST /notes/sync/upsert` | NoteUpsert; attachments must already exist as blobs (D14) |
| `notes_sync_tombstone` | W | `POST /notes/sync/tombstone` | `{source_system, source_workspace, source_doc_ids:[str]}` |
| `request_attachment_upload` | W | `POST /attachments/upload-url` | `{sha256, mime, size_bytes, filename}` → the PUT URL, for file-capable agents to `curl -T` |
| `propose_note_enrichment` | R | `POST /notes/{id}/propose` | `{note_id, llm?:bool}` → Proposal |
| `confirm_note_enrichment` | W | `POST /notes/{id}/confirm` | ConfirmBody + `note_id` |

Host tools call REST via `api_call` and return dicts; `mcp_server` handlers call `notes_access`/`notes_enrich` directly; registry lambdas capture `user_id` (house pattern `mcp_registry.py:3385`).

## A.4 Upload protocol (CLI or any file-capable agent)
```
1. For each attachment: sha256 = SHA-256(bytes); mime from extension (webp/png/jpg/gif/avif/svg/pdf/…).
2. POST /attachments/upload-url {sha256, mime, size_bytes, filename}
   → exists → done.  → upload → PUT {upload_url} with raw bytes (Content-Type: mime, Content-Length: size) → 201 {blob_id}.
   Tickets: single-use, 15 min, bound to (user, sha256, mime, size); the server re-hashes on receipt.
3. POST /notes/sync/upsert with attachments[] (sha256, filename, mime, size_bytes, ref_in_markdown).
   The server links existing blobs; any sha256 not yet uploaded is returned in missing_attachments → repeat step 2 → re-upsert (idempotent).
   Recommended order for the CLI: upload first, upsert once (one round trip when nothing is missing).
4. Verification: GET /notes/{id} → content_hash must equal the local hash; `arp-notes verify` compares body bytes too.
```

## A.5 CLI ↔ server wire format and CLI state
- Wire = A.2 JSON over HTTPS with `Authorization: Bearer pt_…` (a PT API token from Profile → API Tokens; `ARP_NOTES_TOKEN` env or `arp-notes login --app pt --url https://practicetracker.arpinator.com`). Apps are registered by name in `~/.config/arp-notes/config.toml` (`[apps.pt] url=…`); the protocol is app-neutral — JJF would expose the same routes.
- `arp-notes scan <paths…> --app pt [--json]`: resolves embeds (Obsidian rule: by filename anywhere in the vault, shortest path wins), computes hashes, fetches the manifest, prints `{new:[], changed:[], renamed:[], unchanged:[], deleted:[]}` (renamed = same `arp_id`, different path). **No writes.**
- `arp-notes sync <paths…> --app pt [--dry-run] [--json] [--no-write-id] [--kind masterclass] [--verify]`: writes `arp_id` where missing (D1), runs A.4, prints `{synced:[{path, note_id, outcome, uploaded:[sha256]}], errors:[]}`. Exit 0 only if no errors.
- `arp-notes tombstone --app pt <arp_id…>` and `arp-notes status --app pt` (last sync per path from the manifest).
- `arp-notes pull --app pt [<arp_id…>|--all-app-notes] --to <folder> [--with-enrichment] [--enrichment-style frontmatter|companion]` (rev 2, §3.7): writes notes as Markdown + attachments to the folder, embeds rewritten to relative paths, `arp_id` in frontmatter — a later `sync` of the folder round-trips to the same notes. Enrichment export is opt-in.
- `arp-notes capabilities --app pt` (rev 2): prints the host's `GET /notes/capabilities` answer, so a driving LLM knows what this host supports before syncing.
- State: `~/.config/arp-notes/state/<app>-<workspace>.json` caches `{path → arp_id, sha256, synced_at}` as an optimisation only; the server manifest is the truth.
- Obsidian adapter rules: `source_workspace` = vault folder basename; title = frontmatter `title` else filename stem; `note_date` = frontmatter `meeting-date`/`date`/`created` if ISO, else a leading `YYYY-MM-DD` in the filename; `person` = first `[[…]]` in `Attendees::`/`presenter:`/`author:` if present; `kind` = `--kind` else heuristics (D8); `frontmatter` = the YAML block parsed leniently (unknown constructs kept as strings); `body_md` = the whole file verbatim (frontmatter included) — PT strips the frontmatter block for display only.

## A.6 Frontend API client types (`frontend/src/lib/notesApi.js`, JSDoc + ajv)
Functions (all via `apiFetch`): `listNotes(params)`, `getNote(id)`, `createNote(body)`, `patchNote(id, body)`, `autosaveNote(id, body_md, version)`, `deleteNote(id)`, `notesForEntity(type, id)`, `proposeEnrichment(id, {llm})`, `confirmEnrichment(id, ConfirmBody)`, `requestUploadUrl({sha256, mime, size_bytes, filename})`, `putUpload(upload_url, file)` (raw `fetch`, no Bearer), `sha256OfFile(file)` (WebCrypto). JSDoc `@typedef`s mirror A.2 one-to-one; `frontend/src/test/fixtures/notes/{note.json, proposal.json, manifest.json}` are generated from a synthetic fixture and are the mocks every web lane uses.


---

# Part 2 · Contract amendments (K§1–K§6)

## K§1 · DDL delta (core `arp_notes/sql/001_notes.sql`, therefore PT `043_notes.sql`)

Core 001 has not shipped, so these go **into** 001 (not a 002). PT migration 043 = core 001 + the PT delta from A.1, copied verbatim.

```sql
-- in CREATE TABLE notes (...), after updated_at:
    proposal JSONB,                             -- cached last Proposal (K§3); NULL = never proposed
    proposed_at TIMESTAMP,                      -- when `proposal` was computed
    review_pending INTEGER NOT NULL DEFAULT 0,  -- K§3 count; drives the "N to review" badges

-- new table, after upload_tickets:
CREATE TABLE IF NOT EXISTS hygiene_dismissals (   -- K§6
    id SERIAL PRIMARY KEY,
    user_id TEXT NOT NULL,
    issue_key TEXT NOT NULL,                    -- HygieneIssue.key (stable, K§6.1)
    reason TEXT,
    dismissed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id, issue_key)
);
```

Rules unchanged from A.1: every statement idempotent (`IF NOT EXISTS`), `user_id TEXT` without FK, the PT runner skips a whole file on error. **No other migration is added in P1.** If an owner answer later needs DDL (K§5), it is PT migration **044**, filed as its own bead.

`activity_log.event_type` values (A.1 constants) gain `note_hygiene_fix` and `note_merge_applied`.

---

## K§2 · REST shape deltas (A.2)

All additive. Clients must tolerate unknown fields.

**NoteSummary** gains:
```
source_workspace?, source_path?,                       -- list row shows "MyVault / One on one meetings/" (Main, NoteDesk)
thumbnail_url?,                                        -- signed content_url of the first image attachment, ≤1 h (Main)
top_links: [{entity_type, entity_id, entity_label}],   -- ≤4 confirmed links, works before movements before composers (Main, ListPhone)
action_count: int,                                     -- links with action_item (Main "3 actions")
review_pending: int,                                   -- K§3 (Main/DayDesk "1 to review", TodayDesk "26 suggestions to review")
duration_min?                                          -- int(frontmatter.duration) when it parses as a whole number, else null (Main "25 min")
```
**Note** gains `review_pending`, `proposed_at?`.

**`GET /notes`** gains `include_deleted=false` (Main "Show deleted"). The response gains
`sync_sources: [{source_system, source_workspace, last_synced_at, note_count}]` for the "Last sync · Obsidian “MyVault” · 2 days ago" line (Main, ListPhone). `source_system=app` is not a value; "Written here" / "Practice Tracker" filter = `origin=app`.

**`GET /notes/by-entity/{entity_type}/{entity_id}`** gains `include_children=true`. With it the server also returns links whose entity is a child of the requested one, using the host's `LinkSchemes.children` (K§4). PT: repertoire → its movements and sections; composer → its repertoire (and their movements). Each returned link carries `via?: {entity_type, entity_id}` when it matched through a child. This feeds the piece page "9 passages about this piece" grouped by movement and the composer page "Pieces it covers" (PieceDesk, PiecePhone).

**Proposal / ProposedLink / candidates**
```
Proposal        += cached: bool, proposed_at
ProposedLink    += mention_count?            -- composer rows: "Mentioned 14 times" (ReviewDesk)
candidate       += duplicate_group?: string  -- same value = same work/composer by K§4 dedupe key; UI shows "Three look like the same book" (ReviewDesk)
unresolved[]    += kind_hint?: 'work'|'composer'|'movement'|'technique'|'person', composer_label?   -- "WTC Book 1 · Bach" (ReviewDesk seeds)
```
**`POST /notes/{id}/propose`** gains `refresh=false`. Without refresh it returns the cached proposal (K§3) when one exists, else computes, caches and returns. `llm=true` keeps A.2's 503 `llm_disabled` rule.

**ConfirmBody** gains
```
deferred?: [{mention, anchor?}]        -- ambiguous items the user left for later ("Debussy pick left for later", ActivityDesk)
someday?:  [{mention, kind_hint?, composer_label?, anchor?, quote?}]   -- K§5; 422 {"error":"someday_unsupported"} when capabilities.someday=false
```
**ConfirmResult** gains `someday_created: int`, `review_pending: int`.

**`GET /notes/capabilities`** gains
```
someday: bool                          -- host persists "someday" seeds (K§5)
hygiene: bool                          -- hygiene block + tools available (K§6)
propose_on_sync: 'off'|'search'|'judge'  -- K§3; PT: 'search'
judge: string|null                     -- e.g. 'jev-choice>haiku' | 'jev-choice' | null (K§4)
```
The editor's policy footer ("This app allows Images and PDFs up to 25 MB · export to Markdown on", EditorDesk) is rendered **from this response**, never hard-coded.

New endpoints for hygiene and tombstones are in K§6.

---

## K§3 · Review state: cached proposals (architect default **[OWNER Q1]**)

**Why.** The ADR made propose stateless (§1.13). The approved mockups show counts that need state: "1 to review" (list, Day card), "26 suggestions to review" (Today strip), and the composer page's "Mentioned, not in your library" (PiecePhone). Re-running the resolver per list row would put the judge on every page load.

**Design.** The server caches the last Proposal on the note (`notes.proposal`, `proposed_at`) and keeps `review_pending` current. Confirm stays stateless in the house sense: the client still sends exactly what it accepted.
1. **When it is computed.** (a) After `sync/upsert` with outcome `created` or `updated`, when `capabilities.propose_on_sync != 'off'` (PT: `'search'` = candidate generation only, no judge, so sync never waits on AI). (b) On `POST /propose` with no cache or `refresh=true`. That call runs the full pipeline, judge included.
2. **The count.** Before any confirm: `review_pending = len(links) + len(ambiguous) + len(unresolved) + len(action_items)` of the cached proposal. Here `ambiguous` = ProposedLinks with `candidates`. This reproduces the mockup's 26 = 11 + 3 + 2 + 1 + 6 + 3.
3. **Confirm.** The server removes everything the user saw from the cache except `deferred` items, then sets `review_pending = len(deferred)` (the mockup's "1 to review" after confirm). `rejected` persists as `note_links.status='rejected'` (A.2, unchanged). An unticked item is *skipped*: it is not persisted and not pending.
4. **"Decide later"** (whole sheet, ReviewDesk) makes no call. The cache and the count stay as they are.
5. **Re-sync with a changed body** recomputes the proposal (rule 1a). The ADR's diff rule still applies: nothing re-proposes an `(entity, anchor)` already confirmed or rejected.
6. **Tombstoned notes** get `review_pending = 0` and are never auto-proposed.

Module: `arp_notes/review.py` (bead R1). `sync.upsert` calls `review.after_upsert(...)`, and the confirm route calls `review.apply_confirm(...)`. C0 ships both as no-op stubs.

---

## K§4 · Ports delta (§9.2) and the resolver pipeline

**`LinkSchemes`**, per scheme, in addition to `resolve / search / reconcile`:
```
children(entity_type, entity_id) -> [(entity_type, entity_id)]     optional; powers include_children (K§2)
dedupe_key(candidate) -> str|None                                  optional; equal keys = duplicate rows (Debussy 18/19/26; Bach 7/11)
```
**Chip syntax.** The editor inserts `[@<Title>](<prefix>://<entity_type>/<id>)`, e.g. `[@Études, Op.10](pt://repertoire/35)` (spike ga-mxal.17 §2.2). `NoteBody` also renders PT's existing `[@Title](mention://type/slug)` chips, so pasted PT text keeps working. A chip that does not resolve **keeps its text and stays in the Markdown**, shown as "· not found" (EditorDesk).

**`Judge`** (exact signatures; core module `arp_notes/judges.py`):
```
Mention    {text, quote, anchor?, context: {composer?, opus?, note_title, note_kind}}
Candidate  {entity_type, entity_id, entity_label, score, duplicate_group?, children?: [Candidate]}   -- children = stage-2 movements
Judgement  {choice: Candidate|None, confidence: float 0..1, judge: str, stage: 'work'|'movement'}
Judge.judge(mention, candidates) -> Judgement
```
Reference judges in core: `JevChoiceJudge(api_key, url, model='jev-1.13.0', timeout_s=2.0)` (one Choice question per stage with an explicit `none`; request shape = JJF `backend/src/llm/jev_client.py:75-149`); `LlmJudge(complete: Callable[[str], str], name)` (the host injects the provider call; the core imports no provider SDK); `ChainJudge(primary, escalate=None, threshold=0.5)`.

**Pipeline** (`enrich.propose`, ADR §3.4, build order per D5):
1. The **core tokeniser** yields spans with carried context. Example: an opus line with no composer inherits the note's dominant composer (the spike's "opus numbers refer to Chopin unless another composer is named").
2. **Host `reconcile(spans)`** returns candidates. PT issues multi-variant `picker_search` queries per span (the spike showed literal full-mention queries return nothing) and ranks movements by number.
3. **Duplicate collapse.** Candidates with equal `dedupe_key` collapse to one cluster before the judge sees them.
4. **Judge** (if configured). Choice `none` means unresolved. If confidence < `threshold` and `escalate` is set, the escalation judge runs. If confidence < `threshold` and nothing escalates, the item is emitted **ambiguous** (with `candidates`), never dropped and never force-linked.
5. **No judge configured, or the judge raised** (`JevUnavailableError`, timeout): degrade to search-only. A single strong candidate becomes a link with confidence = generator score; several become ambiguous. Sync never depends on AI.
6. **Clusters.** If the chosen cluster has >1 member, the link is emitted ambiguous with `candidates` = cluster members + other near candidates, sharing `duplicate_group`. The user links **one** (owner 18:21: no merge in the sheet), and a `duplicate_entities` hygiene issue is raised (K§6).

**Confidence bands → UI.** high ≥ 0.8, medium 0.5–0.8, low < 0.5. The UI **pre-ticks high and medium** (owner 18:21: medium-confidence composer links pre-ticked = yes) and leaves low unticked (ReviewDesk techniques).

**PT wiring.** `judge = ChainJudge(JevChoiceJudge(TYPESAFE_API_KEY), escalate=LlmJudge(PT Haiku 5.5 call) only when NOTES_LLM_ENRICH=1, threshold=0.5)`. Model id `claude-haiku-5-5`, through PT's existing provider adapter. Jev price for the record: `jev-1.13.0` input $0.042/MTok, output free (JJF `backend/src/llm/pricing.py:42-44`), so about $0.00005 per mention at the spike's ~1,270 input tokens.

---

## K§5 · "Someday" seeds **[OWNER Q2 — gated]**

The mockups let the user switch on unresolved mentions as "someday" ideas: "Switch on to keep one as a 'someday' idea. Nothing is added to your repertoire otherwise." (ReviewDesk, ReviewPhone; composer page "Save one as someday…", PiecePhone). **No mockup shows where saved someday ideas appear later.** Until the owner answers, `capabilities.someday=false` and the UI hides the toggles (ProposalReview renders them only when the host passes `onSomeday`). **Proposed default:** a `practice_backlog` row (`source='note'`, `lane='someday'`, text = "<mention> · <composer_label>"), left out of the default backlog views and listed on the composer page. No DDL is needed, because `lane` is a comment vocabulary (`schema_postgres.sql:356`). Bead S1 implements whatever the owner picks.

---

## K§6 · Hygiene (ga-mxal.24)

### K§6.1 Shapes (`arp_notes/schemas/hygiene_*.json`)
```
HygieneIssue {
  key: string,            -- stable: '<kind>:<entity_type>:<sorted ids joined by ,>' | '<kind>:note:<id>'
  kind: 'duplicate_entities'|'tombstoned_note'|'pending_review'|'orphaned_links'|'unreferenced_blobs'|'unresolved_mentions',
  severity: 'info'|'warn'|'action',
  title: string, explanation: string,           -- plain language for the client LLM to relay
  subjects: [{entity_type, entity_id, label}],
  fixes: [{label, tool, arguments: object, dry_run_first: bool, reversible: bool}],
  detected_by: 'core'|'host'
}
HygieneBlock { issues: [HygieneIssue], total: int, truncated: bool }   -- ≤10 issues per block, most severe first
```
Dismissed issues (`hygiene_dismissals`, K§1) are filtered out. An issue whose subjects change gets a new key, so it comes back.

### K§6.2 Where the block appears
REST responses of `GET /notes` (collection scope), `GET /notes/{id}`, `POST /notes/{id}/propose` and `POST /notes/sync/upsert` (note scope) carry `hygiene: HygieneBlock` **only when `include_hygiene=true`** is passed. The MCP handlers and PT's FastMCP host always pass it; the web UI never does. Detectors: **core** = tombstoned_note, pending_review (review_pending > 0 and proposed_at older than 7 days), orphaned_links, unreferenced_blobs (refcount 0, older than 30 days), unresolved_mentions. **Host** (`HostConfig.hygiene.detect(user_id, scope)`) = PT duplicate_entities (repertoire, composers) using the K§4 dedupe key.

### K§6.3 Endpoints (A.2 style) and MCP tools (A.3 count 13 → 17)
```
GET  /notes/hygiene?scope=all|note:<id>                                    → HygieneBlock              (no MCP tool: list_notes/get_note carry it)
POST /hygiene/dismiss          {issue_key, reason?}                          → {dismissed: true}          MCP dismiss_issue (W)
POST /notes/{id}/resolve-tombstone {action: 'keep'|'delete'}                 → {note_id, action}          MCP resolve_tombstone (W)
POST /hygiene/apply-fix        {issue_key, fix_index, confirm_token?}        → no token: {dry_run: true, plan, confirm_token, expires_at} | token: {applied: true, result}   MCP apply_fix (W)
POST /hygiene/merge-entities   {entity_type, keep_id, merge_ids:[int], dry_run: true, confirm_token?}  → dry run: {plan, confirm_token, expires_at} | apply: {applied: true, audit_event_id}   MCP merge_entities (W)
```
- `resolve_tombstone keep` = the note mockup's "Keep copy" (NotePhone): dismiss the `tombstoned_note` issue; the note stays hidden from feeds. `delete` = "Delete from PT…" = `DELETE /notes/{id}` (owner 18:21: yes).
- **Dry run first, always.** `confirm_token` = HMAC(signer secret, user_id + canonical plan JSON), 10-minute TTL. Applying with a token whose plan no longer matches the current state is refused with 409 `plan_changed`.
- `merge_entities` calls the host port `HostConfig.hygiene.merge(entity_type, keep_id, merge_ids, dry_run) -> MergePlan`, where `MergePlan = {entity_type, keep, merge: [..], moves: [{table, column, rows}], conflicts: [{table, detail}], reversible: false, warnings: [..]}`. Every apply is audited: activity_log `note_merge_applied` with the full plan and the pre-merge row snapshots in `details_json`. It is "audited", not "reversible" (ga-mxal.24 allows either).
- **[OWNER Q3]** Apply-mode `merge_entities` in PT (bead H3b) is gated until the owner has seen one real dry-run plan (Debussy Préludes 18/19/26, Bach 7/11). Detection, dismiss, resolve_tombstone, apply_fix for non-merge fixes and dry-run merge plans all ship in P1.

