# arp-notes (CLI)

```
uvx arp-notes --help
```

The CLI moves verbatim bytes between a notes tool (Obsidian first) and an arp-notes host app. It
never carries note text through an LLM. Wire format: [`PROTOCOL.md`](../../PROTOCOL.md).

Subcommands: `login`, `config`, `capabilities`, `scan`, `status`, `sync`, `verify`, `tombstone`,
`pull` (this page), and `init`, `conformance`, which are stubs until their lanes land (a stub
prints `not implemented` and exits 2).

Exit codes: `0` ok, `1` a runtime failure (network, HTTP error, protocol mismatch, a file that
could not be scanned), `2` bad input or configuration (unknown app, vault root, missing path).

## Usage

### Connect an app

```
arp-notes login --app pt --url https://practicetracker.arpinator.com
```

Registers the app in `~/.config/arp-notes/config.toml` (override the directory with
`ARP_NOTES_CONFIG_DIR`; `XDG_CONFIG_HOME` is honoured), checks the token against
`GET /notes/capabilities`, and stores the token in the OS keyring. The token is read from one line of
stdin with `--token-stdin`, else from `ARP_NOTES_TOKEN`, else prompted for. It is never written to
`config.toml` and never printed.

```toml
[apps.pt]
url = "https://practicetracker.arpinator.com"
# api_prefix = "/api/v1"   # where the host mounts the notes routes; this is the default
```

Without the optional keyring (`uvx --with keyring arp-notes ...`, or `pip install
'arp-notes[keyring]'`), set `ARP_NOTES_TOKEN` for each run; it always wins over the keyring.
`arp-notes config` shows the registered apps and whether a token is available.

The CLI refuses a host whose `protocol` major is not `1`.

### What does this host support?

```
arp-notes capabilities --app pt
```

Prints the host's `GET /notes/capabilities` answer (attachment policy, limits, kinds, export,
hygiene, ...), so a driving LLM knows what to expect before it syncs.

### What would a sync do? (no writes)

```
arp-notes scan "Masterclasses/" "Meetings/2026-10-18 Roy.md" --app pt [--json]
```

Takes explicit files and folders inside an Obsidian vault (never a whole vault: a folder that
contains `.obsidian/` is refused). The vault is the nearest ancestor with `.obsidian/`, and its folder
name is the `source_workspace`. Scan reads the notes and fetches that workspace's manifest; it
writes nothing locally or on the host. It prints `{new, changed, renamed, unchanged, deleted,
errors}`:

| bucket | meaning |
|---|---|
| `new` | no `arp_id` in the frontmatter yet, or an `arp_id` the host has never seen |
| `changed` | known, same path, but the file bytes or the set of attachments differ, or the host has it tombstoned and the file is back |
| `renamed` | known `arp_id` at a different path (`old_path`; `content_changed` says whether it was also edited) |
| `unchanged` | known, same path, same bytes, same attachments |
| `deleted` | a live manifest row inside the scanned paths whose `arp_id` no scanned file carries and whose path is gone from disk (a note moved out of the scanned paths looks the same) |
| `errors` | files that could not be classified: unreadable, not Markdown, or two files sharing one `arp_id` |

Each note entry carries `path` (vault-relative, `/`-separated), `content_hash` (SHA-256 of the file
bytes), `arp_id`, and `attachments`: one `{ref, path, sha256, size_bytes}` per distinct embed, plus
`unresolved_embeds` for embeds that match no vault file.

Embeds are resolved the way Obsidian does: `![[name.png]]` by filename anywhere in the vault, shortest
path wins; `![[folder/name.png]]` by path suffix; standard `![alt](path/name.png)` relative to the
note, then to the vault root, then by filename. A size or alias suffix (`![[name.png|300]]`) is
kept in `ref` and ignored for matching. External URLs, `![[Other note]]` transclusions, and anything
inside code spans or fences are not attachments. Dot-folders (`.obsidian`, `.git`, `.trash`) are
skipped.

### Last sync per path

```
arp-notes status --app pt [--workspace Dave2025]... [--json]
```

Read from the server manifest. Without `--workspace`, every source the host lists in
`sync_sources` (`GET /notes`) is shown.

### Sync notes

```
arp-notes sync "Masterclasses/" --app pt [--dry-run] [--json] [--no-write-id] [--kind masterclass] [--verify]
```

Takes the same explicit files and folders as `scan`. For each Markdown note:

1. **`arp_id`.** A note without one gets exactly one line, `arp_id: <uuid4>`, inserted right after
   the opening `---` (a note with no frontmatter gets a three-line block in front). This is the only
   write the CLI ever makes to a vault; every other byte is unchanged, whatever the line endings,
   BOM, Templater expressions, dataview fields or keys with spaces. The write goes to a dot-file and
   is renamed over the note, and is refused if the note changed on disk meanwhile.
   `--no-write-id` writes nothing: a note with no `arp_id` is identified by its path, and renaming
   it later makes the host see a new note.
2. **Hash** of the file as it is after that write (`content_hash`, SHA-256 of the bytes).
3. **Upload first.** Each distinct attachment the host does not already hold for the note:
   `POST /attachments/upload-url`, then `PUT` of the raw bytes to the returned URL with
   `Content-Type` and `Content-Length` and no Bearer token. Identical bytes (two embeds, two
   notes) are sent once per run.
4. **One upsert.** `POST /notes/sync/upsert` with the whole file as `body_md`; if the host still
   reports `missing_attachments` (or `409 blob_missing`), those are uploaded and the upsert is
   repeated once.

Title, `note_date`, `person` and `kind` come from the note (frontmatter `title`, else the filename;
`meeting-date`/`date`/`created`, else a leading `YYYY-MM-DD` in the filename; the first `[[…]]`
after `Attendees::`, `presenter` or `author`; `--kind`, else guessed from the title and tags). The
`frontmatter` sent is a lenient read of the block with every value kept as a string.

Prints `{synced: [{path, note_id, outcome, uploaded: [sha256]}], errors: []}` and exits 1 if any
note failed (the rest are still synced). Additive keys appear only when relevant: `workspace`,
`renamed_from`, `unresolved_embeds`, `verified`, and a top-level `warnings`. `outcome` is the
host's `created`, `updated` or `unchanged`.

`--dry-run` reads the manifest and prints what would happen (`would_create`, `would_update`,
`unchanged`, with `would_upload` and `would_write_id`); it writes nothing, locally or on the host.
A host that does not accept attachments gets the notes without them, with a warning. There is no
local state file: the host manifest is fetched on every run and is the truth.

### Verify byte for byte

```
arp-notes verify "Masterclasses/" --app pt [--json]
arp-notes sync "Masterclasses/" --app pt --verify
```

Downloads each note (`GET /notes/{id}`) and checks that its `content_hash` equals the SHA-256 of the
local file and that its `body_md`, as UTF-8, equals the file's bytes. This is how "the LLM did not
paraphrase" is proven. `verify` finds the note id by matching the manifest path to `GET /notes`
rows (the manifest carries no id), and also checks the note's `source_doc_id`. Exits 1 on any
mismatch.

### Tombstone

```
arp-notes tombstone <arp_id>... --app pt [--workspace Dave2025] [--json]
```

Tells the host the source of those notes was deleted (`POST /notes/sync/tombstone`); the host keeps
the body and hides the note. Without `--workspace` each id is looked up in the manifests of the
sources the host lists. Prints `{tombstoned, unknown}`; exits 1 if any id is unknown.

### Pull notes out (export)

```
arp-notes pull --app pt --all-app-notes --to "Dave2025/From PT" [--force] [--json]
arp-notes pull <arp_id|note id>... --app pt --to "Dave2025/From PT"
arp-notes pull --app pt --all-app-notes --to ... --with-enrichment [--enrichment-style frontmatter|companion]
```

Export is first-class (ADR §3.7): each note comes from `GET /notes/{id}/export` as `<title>.md` with
`arp_id` in its frontmatter, and its attachments are downloaded beside it from the signed URLs
(hash-checked; the Bearer token is never sent to them). Embeds are rewritten to point at those files
and keep their syntax, alias and size (`![[Attachments/a.png|300]]` -> `![[a.png|300]]`,
`![shot](attachment://7)` -> `![shot](shot.png)`); embeds inside code are left alone. An imported
note comes back byte for byte, so `scan` then calls it `unchanged` and `sync --verify` finds the same
body and the same sha256s. Name notes by `arp_id` (a synced note) or by numeric note id; an
app-authored note has no source `arp_id`, so use its id or `--all-app-notes`.

Nothing in the folder is overwritten by surprise:

- a note already in the folder (found by `arp_id`, wherever it sits) is updated in place; if its
  content differs from the host's (ignoring `exported_at`, which changes on every export) pull
  refuses and says so, until `--force`;
- a different note, or a file of yours, that holds the wanted name is left alone and the new file is
  numbered (`Lesson (2).md`); an attachment name taken by other bytes is numbered the same way,
  even with `--force`;
- a refused note writes nothing, not even its attachments.

Enrichment (links, takeaways, action items) is opt-in. `frontmatter` adds `arp_links`,
`arp_takeaways` and `arp_actions` to the note; `companion` leaves the note alone and writes
`<title>.arp.md` beside it (a second request). The companion repeats the note's `arp_id`, so keep it
out of folders you `sync`. Prints `{pulled, errors}` (`outcome`: `created`, `unchanged`, `updated`);
exits 1 if any note failed.

## Adding a subcommand

`arp_notes_cli.main` discovers every module in the package. A module contributes subcommands by
defining `register(subparsers)`; the handler it sets with `parser.set_defaults(func=...)` takes the
parsed `argparse.Namespace` and returns the process exit code. See `arp_notes_cli/registry.py`.

For API calls, use `arp_notes_cli.client.open_client(app)` (a `NotesClient` with the Bearer token and
`request(method, path, params=, json=)`), and wrap the command body in `client.run_command(name,
body)` so config and HTTP errors become one stderr line and the right exit code. Per-note facts
(hashes, `arp_id`, resolved embeds) come from `scan.scan_vault_notes(paths)`.
