# Reviewing a proposal and confirming it

Contract: `PROTOCOL.md` (proposal and confirm shapes), K§2, K§3, K§4.

`propose_note_enrichment {note_id}` returns a Proposal:

```
{ note_id, cached, proposed_at,
  links:        [ProposedLink],      # candidates present => ambiguous
  action_items: [ProposedAction],
  takeaways:    [string],
  unresolved:   [UnresolvedMention], # mentions the app could not match
  generated_by: ["resolver" | "llm"], hygiene? }
```

## Show it in four groups

**1. Links** — `links` entries with no `candidates`. Group by `confidence`:

| Band | Range | Show as | Default |
|---|---|---|---|
| high | ≥ 0.8 | "Confident" | ticked |
| medium | 0.5 – 0.8 | "Likely" | ticked |
| low | < 0.5 | "Unsure" | unticked |

Each row: the `entity_label` (and its `entity_type` in words), the short `quote`, and the `reason`
when it helps. Composer rows may carry `mention_count`: "Mentioned 14 times". Say plainly that a
ticked row is only a suggestion until they confirm.

**2. Needs your pick** — `links` entries with `candidates`. The user links **one** (or none, or
decides later). Candidates that share a `duplicate_group` are the same work or composer under
different records: say "these three look like the same book", ask for one, and mention you can
have the duplicates tidied up afterwards (hygiene raises `duplicate_entities`). Do not merge
anything in this step. Never choose for the user, whatever the confidence.

**3. Not in your library** — `unresolved`. Say which mentions the app could not match, with
`composer_label` and `kind_hint` when present ("WTC Book 1 · Bach"). Nothing is added to their
library. If `capabilities.someday` is true they may keep one as a "someday" idea; otherwise do not
mention it.

**4. Action items** — `action_items` from the app. Show `text`, the linked entity if any, and the
lane (`practice` = at the instrument, `lesson` = for the next lesson).

## Add your own (Layer 2)

After the app's four groups, add a fifth, **From me**: takeaways ("something you learned") and
action items you drew from the note text. Read the note first (the local file, or `get_note`; the
body is cut at 20,000 characters, `truncated` says so). Rules:

- A takeaway is one sentence in the writer's terms. An action item is imperative, under 120
  characters, with `lane` `practice` or `lesson`.
- Tie an action item to a confirmed link's entity only when the note clearly says so. Use
  `link_index` (the position in the `links` array you will send) or `entity_type` + `entity_id`.
- Use a heading `anchor` only if the proposal or the note's headings give you one. Otherwise omit
  it.
- Do not invent. If the note holds none, say so and send none. Keep it to what the writer wrote.
- Label them as yours and let the user drop or edit any of them.

## Ask, then build the ConfirmBody

Ask once, in plain words: "Shall I add the confident and likely links, with Debussy's Préludes
left for later?" Wait for the answer. Then send **one** `confirm_note_enrichment` per note:

| The user… | Goes into |
|---|---|
| accepts a link (ticked) | `links[]`: `{entity_type, entity_id, anchor, quote, proposed_by, confidence}` copied from the proposal row (for a pick, from the chosen candidate) |
| rejects a link ("not that one") | `rejected[]`: `{entity_type, entity_id, anchor}`. The app will not suggest it again for this note |
| says nothing about / unticks a link | nothing. It is skipped, not rejected |
| postpones a pick ("later") | `deferred[]`: `{mention, anchor}`. `mention` is the ambiguous link's `quote`, or the unresolved item's `mention`; `anchor` is copied from the same row |
| accepts an action item | `action_items[]`: `{text, anchor, entity_type, entity_id, lane, link_index?}` |
| accepts a takeaway | `takeaways[]`: `{anchor, comment}` |
| switches on a "someday" mention | `someday[]`: `{mention, kind_hint, composer_label, anchor, quote}`, only if `capabilities.someday` |

"Decide later" for the whole sheet makes no call at all; the suggestions stay waiting.

The tool's arguments are `{note_id, links, rejected, action_items, takeaways, deferred, someday}`;
send only the keys you have. Result:
`{links_created, links_rejected, backlog_created, takeaways_created, someday_created,
review_pending}`. Tell the user the counts, and that `review_pending` items are still waiting.

If the call fails (for example an entity no longer exists), give the error text; do not retry with
changed ids.
