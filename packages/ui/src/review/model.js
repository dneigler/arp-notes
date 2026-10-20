// ProposalReview state machine: pure functions, no React, no DOM. The component renders what
// buildModel() + derive() return and dispatches the actions reduce() understands, so every rule
// in K§3/K§4 (bands, pre-ticks, deferred vs skipped, link_index) is unit-testable in node.

export const BAND_HIGH = 0.8
export const BAND_MEDIUM = 0.5
export const COLLAPSE_AFTER = 5

export const BAND_ORDER = ['high', 'medium', 'low']
export const GROUP_ORDER = ['pieces', 'composers', 'techniques', 'other']

// K§4: high >= 0.8, medium 0.5-0.8, low < 0.5. The UI pre-ticks high and medium.
export function bandOf(confidence) {
  if (confidence >= BAND_HIGH) return 'high'
  if (confidence >= BAND_MEDIUM) return 'medium'
  return 'low'
}

export const PRE_TICKED = { high: true, medium: true, low: false }

const PIECE_TYPES = new Set(['repertoire', 'movement', 'section', 'work', 'piece'])

export function groupOf(entityType) {
  if (PIECE_TYPES.has(entityType)) return 'pieces'
  if (entityType === 'composer') return 'composers'
  if (entityType === 'technique') return 'techniques'
  return 'other'
}

// K§8: <600 px bottom sheet, <1024 px centred form sheet, else dialog.
export function presentationForWidth(width) {
  if (width < 600) return 'sheet'
  if (width < 1024) return 'formsheet'
  return 'dialog'
}

export function resolvePresentation(presentation, width) {
  if (presentation === 'dialog' || presentation === 'sheet' || presentation === 'formsheet') {
    return presentation
  }
  return presentationForWidth(width ?? 1280)
}

const sameEntity = (a, b) => a.entity_type === b.entity_type && a.entity_id === b.entity_id

// The Proposal -> view model. Nothing here depends on user choices.
export function buildModel(proposal) {
  const links = proposal?.links ?? []
  const sections = new Map()
  const picks = []
  const linkRows = []

  links.forEach((link, index) => {
    if (link.candidates?.length) {
      picks.push({ key: `p${index}`, index, link, candidates: link.candidates })
      return
    }
    const band = bandOf(link.confidence)
    const group = groupOf(link.entity_type)
    const id = `${group}:${band}`
    if (!sections.has(id)) sections.set(id, { id, group, band, rows: [] })
    const row = { key: `l${index}`, index, link, band, sectionId: id }
    sections.get(id).rows.push(row)
    linkRows.push(row)
  })

  const ordered = [...sections.values()].sort(
    (a, b) =>
      GROUP_ORDER.indexOf(a.group) - GROUP_ORDER.indexOf(b.group) ||
      BAND_ORDER.indexOf(a.band) - BAND_ORDER.indexOf(b.band),
  )

  const unresolved = (proposal?.unresolved ?? []).map((item, index) => ({
    key: `u${index}`,
    index,
    item,
  }))

  const actions = (proposal?.action_items ?? []).map((action, index) => ({
    key: `a${index}`,
    index,
    action,
    // The piece the action is about, for its sub-label. Looked up among the proposed links.
    target: findTarget(links, action),
  }))

  return {
    sections: ordered,
    linkRows,
    picks,
    unresolved,
    actions,
    // "N suggestions": the K§3 review_pending count, links + ambiguous + unresolved + actions.
    total: links.length + unresolved.length + actions.length,
  }
}

function findTarget(links, action) {
  if (action.entity_type == null || action.entity_id == null) return null
  const matches = links.filter((l) => sameEntity(l, action))
  if (!matches.length) {
    for (const link of links) {
      const hit = link.candidates?.find((c) => sameEntity(c, action))
      if (hit) return hit.entity_label
    }
    return null
  }
  return (matches.find((l) => l.anchor === action.anchor) ?? matches[0]).entity_label
}

export function initialState(model) {
  const ticked = {}
  for (const row of model.linkRows) ticked[row.key] = PRE_TICKED[row.band]
  const actionOn = {}
  const lanes = {}
  for (const a of model.actions) {
    actionOn[a.key] = true
    lanes[a.key] = a.action.lane
  }
  // picks[key]: undefined = unpicked (deferred), 'skip' = none of these, number = candidate index.
  return { ticked, rejected: {}, picks: {}, actionOn, lanes, someday: {}, expanded: {} }
}

export function reduce(state, action) {
  switch (action.type) {
    case 'toggle':
      return { ...state, ticked: { ...state.ticked, [action.key]: !state.ticked[action.key] } }
    case 'reject':
      return { ...state, rejected: { ...state.rejected, [action.key]: true } }
    case 'undo': {
      const rejected = { ...state.rejected }
      delete rejected[action.key]
      return { ...state, rejected }
    }
    case 'setSection': {
      const ticked = { ...state.ticked }
      for (const key of action.keys) ticked[key] = action.value
      return { ...state, ticked }
    }
    case 'pick':
      return { ...state, picks: { ...state.picks, [action.key]: action.value } }
    case 'toggleAction':
      return { ...state, actionOn: { ...state.actionOn, [action.key]: !state.actionOn[action.key] } }
    case 'setActions': {
      const actionOn = { ...state.actionOn }
      for (const key of action.keys) actionOn[key] = action.value
      return { ...state, actionOn }
    }
    case 'lane':
      return { ...state, lanes: { ...state.lanes, [action.key]: action.value } }
    case 'someday':
      return { ...state, someday: { ...state.someday, [action.key]: action.value } }
    case 'expand':
      return { ...state, expanded: { ...state.expanded, [action.key]: !state.expanded[action.key] } }
    default:
      return state
  }
}

export const isLinkOn = (state, row) => Boolean(state.ticked[row.key]) && !state.rejected[row.key]

export function visibleRows(section, state) {
  if (state.expanded[section.id] || section.rows.length <= COLLAPSE_AFTER) return section.rows
  return section.rows.slice(0, COLLAPSE_AFTER)
}

const strip = (link) => ({
  entity_type: link.entity_type,
  entity_id: link.entity_id,
  anchor: link.anchor ?? null,
  quote: link.quote ?? null,
  proposed_by: link.proposed_by ?? null,
  confidence: link.confidence ?? null,
})

const mentionOf = (link) => link.mention ?? link.entity_label

// Everything the footer and the Confirm button need, and the ConfirmBody itself.
export function derive(model, state, { somedayEnabled = false } = {}) {
  // Confirmed links follow the proposal's own order, whichever kind of row produced them.
  const byIndex = []
  for (const row of model.linkRows) {
    if (isLinkOn(state, row)) byIndex.push([row.index, strip(row.link)])
  }
  const pickSummary = []
  const deferred = []
  for (const pick of model.picks) {
    const choice = state.picks[pick.key]
    const name = mentionOf(pick.link)
    if (typeof choice === 'number') {
      const cand = pick.candidates[choice]
      byIndex.push([
        pick.index,
        strip({ ...pick.link, ...cand, anchor: pick.link.anchor, quote: pick.link.quote, proposed_by: pick.link.proposed_by }),
      ])
      pickSummary.push({ key: pick.key, state: 'picked', name: cand.entity_label })
    } else if (choice === 'skip') {
      pickSummary.push({ key: pick.key, state: 'skipped', name })
    } else {
      deferred.push({ mention: name, anchor: pick.link.anchor ?? null })
      pickSummary.push({ key: pick.key, state: 'later', name })
    }
  }
  byIndex.sort((a, b) => a[0] - b[0])
  const links = byIndex.map(([, link]) => link)

  const rejected = []
  for (const row of model.linkRows) {
    if (state.rejected[row.key]) {
      rejected.push({ entity_type: row.link.entity_type, entity_id: row.link.entity_id, anchor: row.link.anchor ?? null })
    }
  }

  const action_items = []
  for (const a of model.actions) {
    if (!state.actionOn[a.key]) continue
    const src = a.action
    const at = links.findIndex((l) => src.entity_type != null && l.entity_type === src.entity_type && l.entity_id === src.entity_id && l.anchor === (src.anchor ?? null))
    const any = at >= 0 ? at : links.findIndex((l) => src.entity_type != null && l.entity_type === src.entity_type && l.entity_id === src.entity_id)
    action_items.push({
      text: src.text,
      lane: state.lanes[a.key] ?? src.lane,
      anchor: src.anchor ?? null,
      entity_type: src.entity_type ?? null,
      entity_id: src.entity_id ?? null,
      link_index: any >= 0 ? any : null,
    })
  }

  const body = { links, rejected, action_items, deferred }
  let somedayCount = 0
  if (somedayEnabled) {
    body.someday = model.unresolved
      .filter((u) => state.someday[u.key])
      .map((u) => ({
        mention: u.item.mention,
        kind_hint: u.item.kind_hint ?? null,
        composer_label: u.item.composer_label ?? null,
        anchor: u.item.anchor ?? null,
        quote: u.item.quote ?? null,
      }))
    somedayCount = body.someday.length
  }

  const count = links.length + action_items.length + somedayCount
  return {
    body,
    linkCount: links.length,
    backlogCount: action_items.length,
    somedayCount,
    confirmCount: count,
    pickSummary,
    // Confirming with nothing at all would be a no-op for the host.
    empty: count === 0 && rejected.length === 0 && deferred.length === 0,
  }
}

// "Reject all": every proposed target is rejected so none is suggested again for this note.
export function rejectAllBody(model) {
  const rejected = model.linkRows.map((r) => ({
    entity_type: r.link.entity_type,
    entity_id: r.link.entity_id,
    anchor: r.link.anchor ?? null,
  }))
  for (const pick of model.picks) {
    for (const c of pick.candidates) {
      rejected.push({ entity_type: c.entity_type, entity_id: c.entity_id, anchor: pick.link.anchor ?? null })
    }
  }
  return { links: [], rejected, action_items: [], deferred: [] }
}

// Largest set of candidates that share a duplicate_group; 0 when none do (K§2).
export function duplicateCount(candidates) {
  const sizes = new Map()
  for (const c of candidates) {
    if (c.duplicate_group) sizes.set(c.duplicate_group, (sizes.get(c.duplicate_group) ?? 0) + 1)
  }
  const max = Math.max(0, ...sizes.values())
  return max >= 2 ? max : 0
}
