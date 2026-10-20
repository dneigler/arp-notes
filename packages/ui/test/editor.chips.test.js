// @vitest-environment jsdom
import { CompletionContext } from '@codemirror/autocomplete'
import { EditorState } from '@codemirror/state'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { chipText, wikiLinkSource, wikiQuery } from '../src/editor/autocomplete.js'
import { chipRegex, findChips } from '../src/editor/index.js'
import { chipsInBody } from '../src/editor/scan.js'
import { EDITOR_STRINGS } from '../src/editor/strings.js'
import { act, cleanup } from './helpers.js'
import { mountEditor, settle, type } from './editor-helpers.js'

afterEach(cleanup)

const candidate = (entity_type, entity_id, entity_label, extra = {}) => ({ entity_type, entity_id, entity_label, ...extra })

describe('chipRegex', () => {
  it('matches the house chip for its own scheme only', () => {
    const text = 'a [@Études, Op.10](pt://repertoire/35) b [@Venue](jjf://venue/7) c [@Old](mention://repertoire/op-10)'
    expect([...text.matchAll(chipRegex('pt'))].map((m) => m.slice(1))).toEqual([['Études, Op.10', 'repertoire', '35']])
    expect([...text.matchAll(chipRegex('jjf'))].map((m) => m.slice(1))).toEqual([['Venue', 'venue', '7']])
    expect([...text.matchAll(chipRegex('mention'))]).toHaveLength(1)
    expect([...text.matchAll(chipRegex('zz'))]).toHaveLength(0)
  })

  it('escapes regex characters in a prefix', () => {
    expect([...'[@A](my.app://t/1) [@B](myXapp://t/2)'.matchAll(chipRegex('my.app'))]).toHaveLength(1)
  })

  it('does not match plain links, wikilinks, embeds or half-typed chips', () => {
    const re = chipRegex('pt')
    for (const text of ['[x](pt://t/1)', '[[Note]]', '![[a.png]]', '[@A](pt://t)', '[@A](pt://t/ 1)', '[@A] (pt://t/1)', '[@unfinished']) {
      expect(text.match(re)).toBeNull()
    }
  })

  it('is a fresh regex per call (no shared lastIndex)', () => {
    expect(chipRegex('pt')).not.toBe(chipRegex('pt'))
  })
})

describe('findChips / chipsInBody', () => {
  const schemes = [{ prefix: 'pt' }, { prefix: 'jjf' }]

  it('reports positions, decoded ids (digits become numbers) and the scheme, in document order', () => {
    const text = 'x [@V](jjf://venue/7) y [@P%20Q](pt://repertoire/35) z [@S](pt://composer/bach-1)'
    const chips = findChips(text, schemes)
    expect(chips.map((c) => [c.prefix, c.entityType, c.entityId, c.label])).toEqual([
      ['jjf', 'venue', 7, 'V'],
      ['pt', 'repertoire', 35, 'P%20Q'],
      ['pt', 'composer', 'bach-1', 'S'],
    ])
    expect(text.slice(chips[0].from, chips[0].to)).toBe('[@V](jjf://venue/7)')
    expect(chips[0].scheme).toBe(schemes[1])
  })

  it('offsets positions for a slice', () => {
    const [chip] = findChips('[@A](pt://t/1)', schemes, { offset: 100 })
    expect([chip.from, chip.to]).toEqual([100, 114])
  })

  it('leaves chips inside code fences and inline code as plain text', () => {
    const body = ['real [@A](pt://t/1)', '', '```', '[@B](pt://t/2)', '```', '', 'inline `[@C](pt://t/3)` code', '', '    [@D](pt://t/4)', ''].join('\n')
    expect(chipsInBody(body, schemes).map((c) => c.label)).toEqual(['A'])
  })
})

describe('chipText', () => {
  const scheme = { prefix: 'pt' }
  it('writes the house form with the title as label', () => {
    expect(chipText(scheme, candidate('repertoire', 35, 'Études, Op.10'))).toBe('[@Études, Op.10](pt://repertoire/35)')
  })
  it('keeps brackets and line breaks out of the label, and encodes the url parts', () => {
    expect(chipText(scheme, candidate('a b', 'x/y', 'Sonata [Op. 2]\nNo. 1'))).toBe('[@Sonata (Op. 2) No. 1](pt://a%20b/x%2Fy)')
  })
})

describe('the [[ autocomplete source', () => {
  const pt = {
    prefix: 'pt',
    search: vi.fn(async (q) => [
      candidate('repertoire', 18, `Préludes ${q}`, { composer_label: 'Debussy' }),
      candidate('movement', 1003, 'Études, Op.10 · Nº 3'),
      candidate('composer', 13, 'Chopin'),
    ]),
    resolve: () => null,
  }
  const source = wikiLinkSource({ getSchemes: () => [pt], getStrings: () => EDITOR_STRINGS })
  const ctx = (doc, pos = doc.length, explicit = false) => new CompletionContext(EditorState.create({ doc }), pos, explicit)

  it('opens after [[ with typed rows and the host order', async () => {
    const result = await source(ctx('see [[deb'))
    expect(pt.search).toHaveBeenCalledWith('deb')
    expect(result.from).toBe(4)
    expect(result.filter).toBe(false)
    expect(result.options.map((o) => [o.label, o.detail])).toEqual([
      ['Préludes deb', 'Piece · Debussy'],
      ['Études, Op.10 · Nº 3', 'Movement'],
      ['Chopin', 'Composer'],
    ])
  })

  it('opens on a bare [[ (empty query) and keeps a space-containing query', async () => {
    expect((await source(ctx('[['))).from).toBe(0)
    await source(ctx('[[etude op'))
    expect(pt.search).toHaveBeenLastCalledWith('etude op')
  })

  it('is silent when the cursor is not in an open [[', async () => {
    for (const doc of ['plain', '[ [x', '[[done]] and more', '[[done]]', 'a ]] b', '![x](pt://t/1)']) {
      expect(await source(ctx(doc))).toBeNull()
    }
  })

  it('tags an unlisted entity type with a capitalised name', async () => {
    const venue = { prefix: 'jjf', search: async () => [candidate('venue_room', 4, 'Hall')], resolve: () => null }
    const result = await wikiLinkSource({ getSchemes: () => [venue], getStrings: () => EDITOR_STRINGS })(ctx('[[h'))
    expect(result.options[0].detail).toBe('Venue room')
  })

  it('merges several schemes, best score first, and survives one that throws', async () => {
    const a = { prefix: 'a', search: async () => [candidate('t', 1, 'low', { score: 0.2 }), candidate('t', 2, 'high', { score: 0.9 })], resolve: () => null }
    const b = { prefix: 'b', search: async () => [candidate('t', 3, 'mid', { score: 0.5 })], resolve: () => null }
    const bad = { prefix: 'c', search: async () => Promise.reject(new Error('down')), resolve: () => null }
    const result = await wikiLinkSource({ getSchemes: () => [a, bad, b], getStrings: () => EDITOR_STRINGS })(ctx('[[x'))
    expect(result.options.map((o) => o.label)).toEqual(['high', 'mid', 'low'])
  })

  it('returns nothing when no scheme has a match, or when the request was aborted', async () => {
    const none = { prefix: 'n', search: async () => [], resolve: () => null }
    expect(await wikiLinkSource({ getSchemes: () => [none], getStrings: () => EDITOR_STRINGS })(ctx('[[x'))).toBeNull()
    const context = ctx('[[x')
    const slow = { prefix: 's', search: async () => { context.aborted = true; return [candidate('t', 1, 'late')] }, resolve: () => null }
    expect(await wikiLinkSource({ getSchemes: () => [slow], getStrings: () => EDITOR_STRINGS })(context)).toBeNull()
  })

  it('wikiQuery reads the text after the open brackets', () => {
    const at = (doc) => wikiQuery(EditorState.create({ doc, selection: { anchor: doc.length } }))
    expect(at('a [[cho')).toBe('cho')
    expect(at('a [[cho]]')).toBeNull()
    expect(at('a')).toBeNull()
  })
})

describe('Enter inserts the chip, Esc leaves the typed text', () => {
  const schemes = [{ prefix: 'pt', search: async () => [candidate('repertoire', 35, 'Études, Op.10')], resolve: async () => ({ title: 'Études, Op.10' }) }]

  it('applying an option replaces [[q with the house chip and puts the cursor after it', async () => {
    const { view } = mountEditor({ value: 'Played ', schemes })
    view.dispatch({ selection: { anchor: 7 } })
    type(view, '[[etu')
    const source = wikiLinkSource({ getSchemes: () => schemes, getStrings: () => EDITOR_STRINGS })
    const result = await source(new CompletionContext(view.state, view.state.selection.main.head, false))
    act(() => result.options[0].apply(view, result.options[0], result.from, view.state.selection.main.head))
    expect(view.state.doc.toString()).toBe('Played [@Études, Op.10](pt://repertoire/35)')
    expect(view.state.selection.main.head).toBe(view.state.doc.length)
  })

  it('takes hand-typed closing brackets along', async () => {
    const { view } = mountEditor({ value: 'x [[etu]] y', schemes })
    view.dispatch({ selection: { anchor: 7 } })
    const source = wikiLinkSource({ getSchemes: () => schemes, getStrings: () => EDITOR_STRINGS })
    const result = await source(new CompletionContext(view.state, 7, false))
    act(() => result.options[0].apply(view, result.options[0], result.from, 7))
    expect(view.state.doc.toString()).toBe('x [@Études, Op.10](pt://repertoire/35) y')
  })

  it('Esc closes the popover without touching the text (the source is asked, the document is not changed)', async () => {
    const { view } = mountEditor({ value: '', schemes })
    type(view, '[[etu')
    await settle()
    const before = view.state.doc.toString()
    view.contentDOM.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))
    await settle()
    expect(view.state.doc.toString()).toBe(before)
    expect(before).toBe('[[etu')
  })
})
