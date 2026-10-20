---
name: arp-notes
description: >-
  Sync notes from Obsidian into an app that embeds arp-notes (Practice Tracker first), then review
  the links, takeaways and action items it suggests and tidy up afterwards. Use when the user says
  "sync my notes", names a note or masterclass to sync, points at a folder of notes, asks to review
  suggested links for a synced note, or asks about duplicate pieces, deleted-at-source notes or
  other note clean-up in the app. Runs the arp-notes CLI for the bytes and the app's MCP tools for
  review; never syncs a whole vault.
license: MIT
compatibility: >-
  Needs the arp-notes CLI (uvx or on PATH) and a registered app (`arp-notes login`). Review and
  hygiene need the app's arp-notes MCP tools to be connected. Claude Code, or Claude Desktop with
  a local shell.
metadata:
  protocol: "1"
---

# arp-notes

You drive a notes sync. The CLI moves the bytes and proves them with SHA-256; you decide what to
run, show the user what happened, and ask before anything is created or removed.

**Never carry note text yourself.** Do not read a note and re-send it with `create_note` or
`notes_sync_upsert`. Source notes go through `scripts/arp-notes sync` only. Reading a note to
write takeaways is fine.

Run the CLI as `scripts/arp-notes <args>` (this skill's wrapper: `arp-notes` on PATH, else `uvx`).
Always pass `--json` and `--app <name>`; use the app the user names, else the one `arp-notes config`
shows. The MCP tools below belong to the connected app and may carry a server prefix.

## The flow

1. **Capabilities** → 2. **Scope** → 3. **Scan** → 4. **Pick** → 5. **Sync** → 6. **Review** →
7. **Confirm** → 8. **Hygiene**. Do not skip ahead: each step uses what the one before returned.

### 1. Capabilities (first, every session)

Call MCP `notes_capabilities`, or `scripts/arp-notes capabilities --app <app>` when MCP is not
connected. Then respect it:

- `protocol` must be `1`. Otherwise stop and tell the user to update arp-notes.
- `source_systems` must include `obsidian`, else the app does not take Obsidian notes: say so.
- `attachments: false` → notes sync without images or PDFs; tell the user before syncing.
  Otherwise stay inside `mime_allowlist` and `limits.max_attachment_bytes`.
- `kinds` is the list `--kind` may use. `hygiene`, `someday`, `llm_enrich`, `export`,
  `propose_on_sync` say which later steps exist. Do not offer a step the host turned off.

### 2. Scope: only what the user named (never a whole vault)

Sync only the files or folders the user named or clearly meant ("the Roy Howat masterclass" → find
that one note; "my masterclasses folder" → that folder). If you do not know the path, ask, or look
only inside a folder they gave you. If they ask for "everything" or the vault root, decline and ask
which folders. The CLI refuses a folder that contains `.obsidian/`; do not work around it. A
vault holds private things (meetings, money, job notes); the user picks what leaves it.

### 3. Scan (no writes)

`scripts/arp-notes scan <paths…> --app <app> --json` → `{new, changed, renamed, unchanged,
deleted, errors}`. Show it in plain words: "2 new, 1 edited, 1 renamed, 4 already up to date". Name
the notes. Mention `unresolved_embeds` (images the note refers to that are not in the vault) and
anything in `errors` (unreadable file, two notes with the same `arp_id`). Never sync a note that
is in `errors`.

### 4. Pick

Let the user choose from `new`, `changed` and `renamed`. Default to all of those in scope, but ask
when it is more than a handful or the scope was a folder. Leave `unchanged` alone. `deleted` means
the note is gone from the scanned paths (or was moved out of them): list it and ask whether to tell
the app (`scripts/arp-notes tombstone <arp_id…> --app <app> --json`). Never tombstone unasked.

### 5. Sync

**The first time in a conversation that a new note will be synced, explain the `arp_id` line, once:**
"I'll add one line, `arp_id: <uuid>`, to the top of each new note's frontmatter. It is the only
change made to your vault, and it lets the app follow the note when you rename or move it. Nothing
else in the file changes." Offer `--no-write-id` (then renaming the note later makes the app see a
new note). If the user is unsure, show `sync --dry-run --json` first: it writes nothing anywhere.

Then `scripts/arp-notes sync <paths…> --app <app> --json [--kind <kind>] [--verify]`. Use `--kind`
only when the user says what kind it is and it is in `capabilities.kinds`. Add `--verify` when the
user wants proof the app holds the exact bytes.

Report each note: `outcome` (`created`, `updated`, `unchanged`), `uploaded` attachments (count),
`renamed_from`, and every entry in `errors` and `warnings`, verbatim and in plain words. Exit code
1 means some notes failed and the rest synced; say which. Keep each `note_id`: step 6 needs it.

### 6. Review the suggestions (cached proposal)

For each note with outcome `created` or `updated`, call MCP `propose_note_enrichment {note_id}`.
It returns the cached proposal the app computed after the sync. Pass `refresh: true` only if the
user asks to recompute. Do not pass `llm: true` unless `capabilities.llm_enrich` is true and the
user wants it. If the MCP tools are not connected, say the review step needs them (or the app's
web page) and stop after step 5.

Show it grouped, following [references/review.md](references/review.md):
**Links** (by confidence: confident, likely, unsure), **Needs your pick**, **Not in your library**,
**Action items**. Then add **your own Layer-2 takeaways and action items**: read the note (the local
file, or MCP `get_note`) and write them yourself, marked as yours so the user can tell. Group
duplicates ("these three look like the same book") and ask for **one** pick.

### 7. Confirm (only after the user says so)

Nothing is created until the user confirms. Ask what to accept, pick, change or leave out. When
they confirm, call MCP `confirm_note_enrichment` once per note with a ConfirmBody built exactly
from what they accepted ([references/review.md](references/review.md) has the mapping):

- ticked suggestions → `links`; ones they rejected → `rejected`; ones they skipped → nothing.
- a pick they want to postpone → `deferred: [{mention, anchor}]`; do not guess a candidate.
- accepted action items and takeaways → `action_items`, `takeaways`.
- `someday` only when `capabilities.someday` is true and the user switched that mention on.

Report the result in words: links created, backlog items, takeaways, how many are still to review.

### 8. Hygiene

Responses from `propose_note_enrichment`, `get_note`, `list_notes` and `notes_sync_upsert` carry a
`hygiene` block. Relay it in plain language, most severe first, using each issue's `title` and
`explanation`, and offer its `fixes`. **Never run a fix, dismissal or merge without the user's
consent**, dry run first, then apply with the `confirm_token`. Details, including tombstones and
merging duplicate pieces: [references/hygiene.md](references/hygiene.md).

## Rules that always hold

- Never invent a note id, `arp_id`, issue key, `confirm_token` or entity id; copy them from tool
  output.
- Never pick between candidates for the user, and never confirm links they have not seen.
- Never delete, merge or tombstone without a clear yes to that specific action.
- If a tool errors, report the error text and stop that step; do not retry with guessed arguments.
- If this skill and a host's `notes_capabilities` disagree, the host's answer wins.
- Do not paste the user's note text into chat beyond a short quote needed for a decision.
