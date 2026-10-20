# arp-notes skill

An [Agent Skill](https://agentskills.io) that lets Claude sync Obsidian notes into an app that
embeds arp-notes (Practice Tracker first), review the links and action items the app suggests, and
tidy up afterwards. The skill is the "LLM drives" half of the project's third rule; the
[`arp-notes` CLI](../../packages/cli/README.md) is the "bytes" half. Claude never carries note text.

```
capabilities → scan → pick → sync → review (cached proposal) → confirm → hygiene
```

## Install

Claude Code, for every project (replace the tag with the one you want):

```bash
mkdir -p ~/.claude/skills && curl -fsSL https://github.com/dneigler/arp-notes/archive/refs/tags/v0.1.0.tar.gz | tar -xz --strip-components=2 -C ~/.claude/skills arp-notes-0.1.0/skills/arp-notes
```

For one project, use `.claude/skills` in the project instead of `~/.claude/skills`.

Claude Desktop: zip the folder (`cd skills && zip -r arp-notes.zip arp-notes`) and add it under
Settings → Capabilities → Skills. Desktop needs a way to run the CLI on your machine (the Claude
Code tab, or a shell connector). Without one, Claude still does the review and clean-up through
the app's connector and prints the exact `arp-notes` command for you to run for the sync step.

You also need:

1. **uv**, which gives the skill `uvx` (it runs the CLI with no install step), or the CLI itself on
   PATH. `scripts/arp-notes` picks whichever exists; set `ARP_NOTES_REF` to use another tag or
   branch.
2. **An app registered once**: `scripts/arp-notes login --app pt --url https://practicetracker.arpinator.com`
   (a Practice Tracker API token from Profile → API Tokens, read from `ARP_NOTES_TOKEN` or a
   prompt, stored in your keyring, never in a file).
3. **The app's MCP connector** in Claude, for the review and clean-up steps.

## Try it: a walkthrough on the synthetic fixture

The fixture is [`packages/core/tests/fixtures/enrich/masterclass.md`](../../packages/core/tests/fixtures/enrich/masterclass.md),
a made-up masterclass note (Ada Quill, Chopin études, a Debussy pick, mentions the app cannot
match). Below, the vault is `Dave2025` and the note sits in `Masterclasses/`. The `scan` output
is real, captured against a stand-in host; the `sync` line is abbreviated; what Claude says and the
suggestions are the shape the skill asks for, not a recording of a live app.

> **You:** sync my Ada Quill masterclass note

**Claude** calls `notes_capabilities` (protocol 1, Obsidian accepted, attachments allowed up to
25 MB, hygiene on), then scans only that note:

```
$ arp-notes scan "Masterclasses/2026-10-18 Ada Quill.md" --app pt --json
{
  "new": [
    {
      "path": "Masterclasses/2026-10-18 Ada Quill.md",
      "workspace": "Dave2025",
      "arp_id": null,
      "content_hash": "7497f19ee39e6af87f629b9be0cf9f7e49ef2ef3620ad3c64f745d694320817b",
      "size_bytes": 784,
      "attachments": [],
      "unresolved_embeds": []
    }
  ],
  "changed": [], "renamed": [], "unchanged": [], "deleted": [], "errors": []
}
```

> **Claude:** One new note, “2026-10-18 Ada Quill”. Before I sync it: I'll add one line, `arp_id:
> <uuid>`, to the top of the note's frontmatter. It's the only change I make to your vault, and it
> lets the app follow the note if you rename or move it. OK?
>
> **You:** yes

```
$ arp-notes sync "Masterclasses/2026-10-18 Ada Quill.md" --app pt --json
{"synced": [{"path": "Masterclasses/2026-10-18 Ada Quill.md", "workspace": "Dave2025",
             "note_id": 41, "outcome": "created", "uploaded": []}], "errors": []}
```

> **Claude:** Synced as note 41 (created, nothing to upload). I've asked the app what it
> recognises in it…

**Claude** calls `propose_note_enrichment {note_id: 41}` and shows the cached proposal:

> **Confident (ticked):** Chopin Études, Op. 10 · Op. 10 no. 3 · Op. 25 no. 1
> **Likely (ticked):** Bach, BWV 814
> **Needs your pick:** “Debussy Préludes” matches three records that look like the same book. Which one?
> **Not in your library:** Fauré, Duparc, WTC Book 1 · Bach
> **Action items:** Practise no. 12 slowly, drop the hand
> **From me:** takeaway: “Op. 25 no. 1 should flow like a harp”; action: “Ask Ada about half pedalling in Op. 10 no. 3” (lesson)
>
> Add the confident and likely links and the action items, and leave the Debussy pick for later?
>
> **You:** yes, and drop the lesson one

Only now does Claude call `confirm_note_enrichment` (the links, the practice action, the takeaway,
and `deferred: [{mention: "Debussy Préludes: pick the Book 1 numbering"}]`) and reports: “3
links, 1 backlog item, 1 takeaway added; 1 item still to review.” Then the hygiene block:

> **Claude:** One more thing: the three Debussy records look like duplicates of one book. I can
> show you what merging them would change, with nothing touched yet. Want to see the plan?

If you say yes it runs the dry run, explains the plan, and applies only after a second yes.

## What it will not do

- Sync a whole vault: you name the notes or folders.
- Create, merge or delete anything without your yes to that specific action.
- Pick between candidates for you, or send note text through the model.

## Development

`tests/test_skill.py` keeps this skill honest against the code: its frontmatter, the CLI commands
and flags it names, the MCP tools it calls and the proposal fields it reads must all exist.
