# arp-notes (CLI)

```
uvx arp-notes --help
```

The CLI moves verbatim bytes between a notes tool (Obsidian first) and an arp-notes host app. It
never carries note text through an LLM. Wire format: [`PROTOCOL.md`](../../PROTOCOL.md).

Subcommands: `login`, `config`, `capabilities`, `scan`, `status` (this page), and `sync`,
`verify`, `tombstone`, `pull`, `init`, `conformance`, which are stubs until their lanes land (a
stub prints `not implemented` and exits 2).

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

## Adding a subcommand

`arp_notes_cli.main` discovers every module in the package. A module contributes subcommands by
defining `register(subparsers)`; the handler it sets with `parser.set_defaults(func=...)` takes the
parsed `argparse.Namespace` and returns the process exit code. See `arp_notes_cli/registry.py`.

For API calls, use `arp_notes_cli.client.open_client(app)` (a `NotesClient` with the Bearer token and
`request(method, path, params=, json=)`), and wrap the command body in `client.run_command(name,
body)` so config and HTTP errors become one stderr line and the right exit code. Per-note facts
(hashes, `arp_id`, resolved embeds) come from `scan.scan_vault_notes(paths)`.
