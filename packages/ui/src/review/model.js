// ProposalReview model: the pure part. It buckets a Proposal into the sections the review shows,
// holds the default ticks (K§4 bands) and derives the ConfirmBody (A.2 + K§2/K§3) from what the user
// did. No React in here, so the whole mapping is unit-testable.

/** K§4 confidence bands: high >= 0.8, medium 0.5-0.8, low < 0.5. */
export function band(confidence) {
  if (confidence >= 0.8) return 'high'
  if (confidence >= 0.5) return 'medium'
  return 'low'
}

/** Owner 18:21: high and medium are pre-ticked, low is not. */
export const isPreTicked = (confidence) => band(confidence) !== 'low'

export const entityKey = (type, id) => `${type}:${id}`

/** Beyond this many rows a link section collapses behind "Show N more". */
export const COLLAPSE_AFTER = 5

const BAND_ORDER = ['high', 'medium', 'low']

// A link section is chosen by what the entity is; the band only drives the badge and the default tick.
function sectionOf(entityType) {
  if (entityType === 'composer') return 'composers'
  if (entityType === 'technique') return 'techniques'
  return 'pieces'
}

function duplicateClusterSize(candidates) {
  const counts = new Map()
  for (const c of candidates) {
    if (!c.duplicate_group) continue
    counts.set(c.duplicate_group, (counts.get(c.duplicate_group) ?? 0) + 1)
  }
  return Math.max(0, ...counts.values())
}

/** Buckets a Proposal. Indexes are positions in the proposal's own arrays and are stable for it. */
export function buildModel(proposal) {
  const links = proposal.links ?? []
  const unresolved = proposal.unresolved ?? []
  const actions = proposal.action_items ?? []

  const sections = { pieces: [], composers: [], techniques: [] }
  const groups = []
  links.forEach((link, i) => {
    if (link.candidates?.length) {
      groups.push({
        i,
        link,
        candidates: link.candidates,
        duplicates: duplicateClusterSize(link.candidates),
      })
    } else {
      sections[sectionOf(link.entity_type)].push({ i, link, band: band(link.confidence) })
    }
  })

  const labels = new Map()
  for (const link of links) {
    labels.set(entityKey(link.entity_type, link.entity_id), link.entity_label)
    for (const c of link.candidates ?? []) labels.set(entityKey(c.entity_type, c.entity_id), c.entity_label)
  }

  return {
    sections,
    groups,
    unresolved: unresolved.map((item, i) => ({ i, item })),
    actions: actions.map((item, i) => ({ i, item })),
    labels,
    total: links.length + unresolved.length + actions.length,
    proposal,
  }
}

/** The bands present in a section, high to low, for the heading ("Composers · medium"). */
export function bandsIn(rows) {
  const present = new Set(rows.map((r) => r.band))
  return BAND_ORDER.filter((b) => present.has(b))
}

export function initialState(model) {
  const ticked = new Set()
  for (const rows of Object.values(model.sections)) {
    for (const r of rows) if (isPreTicked(r.link.confidence)) ticked.add(r.i)
  }
  return {
    ticked,
    rejected: new Set(),
    // group link index -> 'skip' | entityKey of the chosen candidate. Absent = not decided yet.
    picks: new Map(),
    someday: new Set(),
    actionOn: new Set(model.actions.map((a) => a.i)),
    lanes: new Map(model.actions.map((a) => [a.i, a.item.lane])),
    expanded: new Set(),
  }
}

export const SKIP = 'skip'

function compact(obj) {
  const out = {}
  for (const [k, v] of Object.entries(obj)) if (v !== null && v !== undefined) out[k] = v
  return out
}

function confirmLink(link, source, confidence) {
  return compact({
    entity_type: source.entity_type,
    entity_id: source.entity_id,
    anchor: link.anchor,
    quote: link.quote,
    proposed_by: link.proposed_by,
    confidence,
  })
}

/**
 * What the user chose, as the ConfirmBody the server expects, plus the numbers the footer shows.
 * `somedayEnabled` is true only when the host passed onSomeday (K§5).
 */
export function derive(model, state, { somedayEnabled = false } = {}) {
  const proposal = model.proposal
  const links = []
  const rejected = []
  const deferred = []
  const groupByIndex = new Map(model.groups.map((g) => [g.i, g]))
  let picked = 0
  let skipped = 0
  let later = 0

  proposal.links.forEach((link, i) => {
    const group = groupByIndex.get(i)
    if (group) {
      const pick = state.picks.get(i)
      if (pick === undefined) {
        later += 1
        // ConfirmBody.deferred names the mention; a ProposedLink has no mention field, so the quote
        // (the note text that raised it) is what the server can show later.
        deferred.push(compact({ mention: link.quote, anchor: link.anchor }))
      } else if (pick === SKIP) {
        skipped += 1
      } else {
        const chosen = group.candidates.find((c) => entityKey(c.entity_type, c.entity_id) === pick)
        if (chosen) {
          picked += 1
          links.push(confirmLink(link, chosen, chosen.confidence))
        }
      }
      return
    }
    if (state.rejected.has(i)) {
      rejected.push(compact({ entity_type: link.entity_type, entity_id: link.entity_id, anchor: link.anchor }))
    } else if (state.ticked.has(i)) {
      links.push(confirmLink(link, link, link.confidence))
    }
  })

  const action_items = []
  for (const { i, item } of model.actions) {
    if (!state.actionOn.has(i)) continue
    let linkIndex = null
    if (item.entity_type && item.entity_id !== null && item.entity_id !== undefined) {
      const same = (l) => l.entity_type === item.entity_type && l.entity_id === item.entity_id
      const exact = links.findIndex((l) => same(l) && (l.anchor ?? null) === (item.anchor ?? null))
      const loose = exact >= 0 ? exact : links.findIndex(same)
      linkIndex = loose >= 0 ? loose : null
    }
    action_items.push(
      compact({
        text: item.text,
        anchor: item.anchor,
        entity_type: item.entity_type,
        entity_id: item.entity_id,
        lane: state.lanes.get(i) ?? item.lane,
        link_index: linkIndex,
      }),
    )
  }

  const someday = []
  if (somedayEnabled) {
    for (const { i, item } of model.unresolved) {
      if (!state.someday.has(i)) continue
      someday.push(
        compact({
          mention: item.mention,
          kind_hint: item.kind_hint,
          composer_label: item.composer_label,
          anchor: item.anchor,
          quote: item.quote,
        }),
      )
    }
  }

  const body = { links, rejected, action_items }
  if (deferred.length) body.deferred = deferred
  if (someday.length) body.someday = someday

  return {
    body,
    counts: {
      links: links.length,
      backlog: action_items.length,
      someday: someday.length,
      confirm: links.length + action_items.length + someday.length,
      picked,
      skipped,
      later,
    },
  }
}

/**
 * Reject all: nothing is linked and every suggested link is rejected, so it is not proposed again.
 * An ambiguous item rejects each of its candidates. Passed to onRejectAll as a ready ConfirmBody.
 */
export function rejectAllBody(model) {
  const groupByIndex = new Map(model.groups.map((g) => [g.i, g]))
  const rejected = []
  const reject = (e, anchor) =>
    rejected.push(compact({ entity_type: e.entity_type, entity_id: e.entity_id, anchor }))
  model.proposal.links.forEach((link, i) => {
    const group = groupByIndex.get(i)
    if (group) for (const c of group.candidates) reject(c, link.anchor)
    else reject(link, link.anchor)
  })
  return { links: [], rejected, action_items: [] }
}
