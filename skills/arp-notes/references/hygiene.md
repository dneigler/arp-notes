# Hygiene: relaying it and fixing things with consent

Contract: K§6. A `hygiene` block is `{issues, total, truncated}`; it is already limited to 10
issues, most severe first, with dismissed ones removed. Present it after the main task, in plain
language, without jargon. `truncated: true` or `total` above what you see → say there are more.

## One issue

```
{ key, kind, severity: info|warn|action, title, explanation,
  subjects: [{entity_type, entity_id, label}],
  fixes: [{label, tool, arguments, dry_run_first, reversible}] }
```

Say the `title` and `explanation` in your own words, name the `subjects` by `label`, then offer
each fix by its `label` and say whether it can be undone (`reversible`). Group by `kind` when there
are several of one sort. Lead with `action`, then `warn`; mention `info` briefly or only if asked.

## Running a fix

A fix is a ready tool call: call `fix.tool` with `fix.arguments`, copied exactly. Only after the
user agrees to **that** fix.

- **`dry_run_first: true`** (tool `apply_fix`, or `merge_entities`): call it without a
  `confirm_token` first. It returns `{dry_run: true, plan, confirm_token, expires_at}` (merge:
  `{plan, confirm_token, expires_at}`). Explain the `plan` in plain words (what is touched, how
  many rows, any `conflicts` or `warnings`, `reversible`). Ask. Only on a clear yes call the same
  tool again **with that `confirm_token`**. Tokens last 10 minutes. On `409 plan_changed` or an
  expired token, the situation changed: run the dry run again and ask again.
- **`dry_run_first: false`** (for example `dismiss_issue`, `resolve_tombstone keep`): still ask,
  then call it.
- Never reuse a token for a different plan, and never fabricate one.

## By kind

| `kind` | Say | Tools |
|---|---|---|
| `tombstoned_note` | "The note was deleted in Obsidian; the app still keeps a hidden copy." Offer **keep** (hidden, links stay) or **delete** (removed with its links for good) | `resolve_tombstone {note_id, action: keep\|delete}`. `delete` only on an explicit yes to deleting; say it cannot be undone |
| `duplicate_entities` | "Two (or three) records look like the same piece." Offer a merge | `merge_entities {entity_type, keep_id, merge_ids, dry_run: true}` first. Ask which record to keep; do not decide. Merge is audited, not reversible. A host may refuse the apply step until its owner has approved a dry run; report that as it is |
| `pending_review` | "Suggestions in this note have waited over a week." | Offer to go through them: `propose_note_enrichment {note_id}` and the review flow |
| `unresolved_mentions` | "Some mentions could not be matched." | Same: show them with the review flow |
| `orphaned_links` | "Some links point at things that no longer exist." | Follow the issue's `fixes` |
| `unreferenced_blobs` | "Unused attachments are taking space." | `apply_fix` with dry run first; deleting is not reversible |

## Dismissing

`dismiss_issue {issue_key, reason?}` hides an issue. Explain the issue first and dismiss only when
the user wants it hidden ("not now"). It comes back if the things it is about change. Do not
dismiss to tidy up your own report.

## Writes are logged

Applied fixes and merges are written to the app's activity log. Mention that when you apply one.
