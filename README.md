# arp-notes

A portable notes-sync component for AI-forward apps. Your notes stay in the tool you write them
in (Obsidian today; Notion and Apple Notes later; an LLM as an author). arp-notes carries them,
verbatim, into any app that embeds it, and lets that app link a note's passages to its own things
(a piece in a practice tracker, a venue in a gig finder) after you confirm each link.

It is a component for apps to use, not a walled garden: export to Markdown plus attachments is
on by default, and a later sync of the exported folder round-trips to the same notes.

## Three rules

1. **Shared protocol, per-app storage.** Each host app keeps notes in its own database and defines
   its own link schemes (`pt://repertoire/:id`, `jjf://venue/:id`, or any `/thing/:id` pattern).
   The wire protocol ([PROTOCOL.md](PROTOCOL.md)) is app-neutral.
2. **The source owns the body.** A re-sync replaces the body byte for byte. The app owns the
   enrichment (links, takeaways, action items) in a separate layer that a re-sync never clobbers.
3. **The LLM drives but does not carry the bytes.** A small CLI moves verbatim bytes and proves it
   with SHA-256; the Claude skill tells the model when and how to run it. Nothing is created
   without an explicit confirm.

## What is here

| Path | What |
|---|---|
| [`PROTOCOL.md`](PROTOCOL.md) | The wire contract (`protocol_version: 1`). With the conformance kit, this is the product. |
| `packages/core` | `arp-notes-core` (`import arp_notes`): ports, sync, attachments, enrichment, FastAPI routers, MCP tool specs. ORM-free. |
| `packages/cli` | `arp-notes`: scan, sync, pull, verify. `uvx arp-notes` needs no install step. |
| `packages/ui` | `@arpinator/notes-ui`: note view, editor and proposal review, styled only with `--arpn-*` CSS variables. |
| `packages/conformance` | `arp-notes-conformance`: black-box kit that drives any implementation over HTTP and MCP. |
| [`RELEASING.md`](RELEASING.md) | Tags, versions and install-by-tag lines. |

> **Status: scaffold.** Every module exists as a stub with its final signature, so the parts can be
> built in parallel; most bodies raise `NotImplementedError` (the CLI prints `not implemented`)
> until their lane lands.

## Develop

Python 3.12 with [uv](https://docs.astral.sh/uv/); Node for the UI package.

```bash
uv sync --python 3.12
uv run ruff check . && uv run ruff format --check .
uv run pyright
uv run pytest

npm ci
npm run build
npm test
npx playwright install chromium          # once
npm run test:e2e                          # demo harness + axe, light and dark
```

`npm run demo --workspace packages/ui` serves the demo harness at <http://127.0.0.1:4173>.
CI runs all of the above on every push and pull request.

## Licence

MIT. See [LICENSE](LICENSE).
