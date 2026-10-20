import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'
import {
  bandOf,
  buildModel,
  derive,
  initialState,
  presentationForWidth,
  reduce,
  rejectAllBody,
  resolvePresentation,
  visibleRows,
} from '../src/review/model.js'
import { countWord, fmt } from '../src/review/strings.js'
import { howatProposal } from '../demo/fixtures/howat.js'

// The contract's own 26-suggestion example (arp_notes/schemas/examples/Proposal.json).
const example = JSON.parse(
  readFileSync(new URL('../../core/arp_notes/schemas/examples/Proposal.json', import.meta.url), 'utf8'),
)

const run = (proposal, ...actions) => {
  const model = buildModel(proposal)
  let state = initialState(model)
  for (const a of actions) state = reduce(state, a)
  return { model, state, result: derive(model, state, { somedayEnabled: true }) }
}

describe('confidence bands (K§4)', () => {
  it.each([
    [0.95, 'high'],
    [0.8, 'high'],
    [0.79, 'medium'],
    [0.5, 'medium'],
    [0.49, 'low'],
    [0, 'low'],
  ])('%s is %s', (confidence, band) => expect(bandOf(confidence)).toBe(band))
})

describe('presentation', () => {
  it.each([
    [390, 'sheet'],
    [599, 'sheet'],
    [600, 'formsheet'],
    [820, 'formsheet'],
    [1023, 'formsheet'],
    [1024, 'dialog'],
    [1280, 'dialog'],
  ])('auto at %s px is %s', (width, mode) => expect(presentationForWidth(width)).toBe(mode))

  it('an explicit presentation ignores the viewport', () => {
    expect(resolvePresentation('dialog', 390)).toBe('dialog')
    expect(resolvePresentation('sheet', 1600)).toBe('sheet')
    expect(resolvePresentation('auto', 390)).toBe('sheet')
    expect(resolvePresentation(undefined, 820)).toBe('formsheet')
  })
})

describe('the 26-suggestion example Proposal', () => {
  const model = buildModel(example)

  it('splits into the K§3 sections: 11 + 3 + 2 + 1 + 6 + 3', () => {
    expect(model.total).toBe(26)
    expect(model.sections.map((s) => [s.id, s.rows.length])).toEqual([
      ['pieces:high', 11],
      ['composers:medium', 3],
      ['techniques:low', 2],
    ])
    expect(model.picks).toHaveLength(1)
    expect(model.unresolved).toHaveLength(6)
    expect(model.actions).toHaveLength(3)
  })

  it('pre-ticks high and medium and leaves low unticked (owner 18:21)', () => {
    const state = initialState(model)
    const ticked = model.linkRows.filter((r) => state.ticked[r.key]).map((r) => r.band)
    expect(ticked).toHaveLength(14)
    expect(new Set(ticked)).toEqual(new Set(['high', 'medium']))
    for (const row of model.linkRows.filter((r) => r.band === 'low')) expect(state.ticked[row.key]).toBe(false)
  })

  it('default ticks -> ConfirmBody snapshot', () => {
    const { result } = run(example)
    expect(result.linkCount).toBe(14)
    expect(result.backlogCount).toBe(3)
    expect(result.confirmCount).toBe(17)
    expect(result.body).toMatchSnapshot()
  })

  it('every emitted body has the ConfirmBody shape', () => {
    const { result } = run(example)
    const body = result.body
    for (const link of body.links) {
      expect(typeof link.entity_type).toBe('string')
      expect(Number.isInteger(link.entity_id)).toBe(true)
    }
    for (const r of body.rejected) expect(Number.isInteger(r.entity_id)).toBe(true)
    for (const a of body.action_items) {
      expect(['practice', 'lesson']).toContain(a.lane)
      expect(typeof a.text).toBe('string')
    }
    expect(Object.keys(body)).toEqual(['links', 'rejected', 'action_items', 'deferred', 'someday'])
  })

  it('action items carry link_index into body.links', () => {
    const { result } = run(example)
    const [a0, a1, a2] = result.body.action_items
    expect(result.body.links[a0.link_index]).toMatchObject({ entity_type: 'movement', entity_id: 1003 })
    expect(a1.link_index).toBeNull() // no entity
    expect(result.body.links[a2.link_index]).toMatchObject({ entity_type: 'movement', entity_id: 1006 })
  })

  it('collapses sections beyond five rows and expands on request', () => {
    const { model: m, state } = run(example)
    const pieces = m.sections[0]
    expect(visibleRows(pieces, state)).toHaveLength(5)
    expect(visibleRows(pieces, reduce(state, { type: 'expand', key: pieces.id }))).toHaveLength(11)
    expect(visibleRows(m.sections[1], state)).toHaveLength(3)
  })
})

describe('reject / undo', () => {
  it('a rejected row leaves links and is listed in rejected', () => {
    const base = run(example)
    const row = base.model.linkRows[1]
    const { result } = run(example, { type: 'reject', key: row.key })
    expect(result.linkCount).toBe(13)
    expect(result.body.rejected).toEqual([
      { entity_type: row.link.entity_type, entity_id: row.link.entity_id, anchor: row.link.anchor },
    ])
  })

  it('undo restores the row with its earlier tick', () => {
    const base = run(example)
    const row = base.model.linkRows[1]
    const { result } = run(example, { type: 'reject', key: row.key }, { type: 'undo', key: row.key })
    expect(result.linkCount).toBe(14)
    expect(result.body.rejected).toEqual([])
  })

  it('a rejected row that was unticked stays unticked after undo', () => {
    const base = run(example)
    const low = base.model.linkRows.find((r) => r.band === 'low')
    const { result } = run(example, { type: 'reject', key: low.key }, { type: 'undo', key: low.key })
    expect(result.linkCount).toBe(14)
  })

  it('"Untick all" skips rejected rows and a section tick-all round trips', () => {
    const base = run(example)
    const sec = base.model.sections[0]
    const keys = sec.rows.map((r) => r.key)
    const off = run(example, { type: 'setSection', keys, value: false })
    expect(off.result.linkCount).toBe(3)
    const on = run(example, { type: 'setSection', keys, value: false }, { type: 'setSection', keys, value: true })
    expect(on.result.linkCount).toBe(14)
  })

  it('Reject all rejects every proposed target, ambiguous candidates included', () => {
    const body = rejectAllBody(buildModel(example))
    expect(body.links).toEqual([])
    expect(body.action_items).toEqual([])
    expect(body.rejected).toHaveLength(16 + 4) // 16 plain links + the 4 Debussy candidates
  })
})

describe('deferred vs skipped (K§3)', () => {
  const pickKey = buildModel(example).picks[0].key

  it('an ambiguous item left alone is deferred, not skipped', () => {
    const { result } = run(example)
    expect(result.body.deferred).toEqual([{ mention: 'Préludes, Livre 1', anchor: 'debussy' }])
    expect(result.pickSummary).toEqual([{ key: pickKey, state: 'later', name: 'Préludes, Livre 1' }])
  })

  it('"None of these — skip" is neither linked nor deferred', () => {
    const { result } = run(example, { type: 'pick', key: pickKey, value: 'skip' })
    expect(result.body.deferred).toEqual([])
    expect(result.linkCount).toBe(14)
    expect(result.pickSummary[0].state).toBe('skipped')
  })

  it('picking one candidate links exactly that one', () => {
    const { result } = run(example, { type: 'pick', key: pickKey, value: 1 })
    expect(result.body.deferred).toEqual([])
    expect(result.linkCount).toBe(15)
    expect(result.body.links.filter((l) => l.anchor === 'debussy')).toEqual([
      expect.objectContaining({ entity_type: 'repertoire', entity_id: 19, anchor: 'debussy', confidence: 0.54 }),
    ])
  })
})

describe('someday (K§5)', () => {
  it('is left out of the body unless the host enables it', () => {
    const model = buildModel(example)
    const state = reduce(initialState(model), { type: 'someday', key: model.unresolved[0].key, value: true })
    expect(derive(model, state, { somedayEnabled: false }).body).not.toHaveProperty('someday')
    const on = derive(model, state, { somedayEnabled: true })
    expect(on.body.someday).toEqual([
      {
        mention: 'Bach WTC book 1',
        kind_hint: 'work',
        composer_label: 'WTC Book 1 · Bach',
        anchor: null,
        quote: 'Synthetic quote from the note body.',
      },
    ])
    expect(on.confirmCount).toBe(18)
  })
})

describe('the Howat demo fixture matches the mockup', () => {
  it('is 26 suggestions: 11 + 3 + 2 + 1 + 6 + 3', () => {
    const model = buildModel(howatProposal)
    expect(model.total).toBe(26)
    expect(model.sections.map((s) => s.rows.length)).toEqual([11, 3, 2])
    expect(model.picks).toHaveLength(1)
    expect(derive(model, initialState(model)).confirmCount).toBe(17) // "Confirm 17"
  })
})

describe('empty proposals', () => {
  it('build to nothing and disable confirm', () => {
    const { result, model } = run({ note_id: 1, links: [], action_items: [], unresolved: [], takeaways: [] })
    expect(model.total).toBe(0)
    expect(result.empty).toBe(true)
  })
})

describe('strings', () => {
  it('fills placeholders and keeps unknown ones', () => {
    expect(fmt('Link to {target}', { target: 'Chopin' })).toBe('Link to Chopin')
    expect(fmt('{a} {b}', { a: 1 })).toBe('1 {b}')
  })
  it('spells small counts', () => {
    expect(fmt('{Count} look like the same book.', countWord(3))).toBe('Three look like the same book.')
    expect(countWord(12).Count).toBe('12')
  })
})
