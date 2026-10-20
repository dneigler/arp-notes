// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from 'vitest'
import { checkShape } from '../src/api/validate.js'
import { ProposalReview, presentationForWidth } from '../src/review/index.js'
import { band, buildModel, derive, initialState } from '../src/review/model.js'
import { createRoot } from 'react-dom/client'
import { act, cleanup, example, h, mount } from './helpers.js'

afterEach(() => {
  cleanup()
  document.body.style.overflow = ''
})

// The 26-suggestion example: 11 pieces, 3 composers, 2 techniques, 1 ambiguous (Debussy), 6 not in the
// library, 3 action items (K§3.2: 11 + 3 + 2 + 1 + 6 + 3).
const proposal = () => example('Proposal')

function render(props = {}) {
  const calls = { onConfirm: vi.fn(), onDecideLater: vi.fn(), onRejectAll: vi.fn() }
  const container = mount(
    h(ProposalReview, { proposal: proposal(), presentation: 'dialog', noteTitle: '2026-10-18 Roy Howat', ...calls, ...props }),
  )
  return { container, ...calls, props }
}

const q = (c, sel) => c.querySelector(sel)
const qa = (c, sel) => [...c.querySelectorAll(sel)]
const byLabel = (c, label) => qa(c, 'input, button').find((el) => el.getAttribute('aria-label') === label)
const byText = (c, text) => qa(c, 'button').find((el) => el.textContent.trim() === text)
const click = (el) => act(() => el.click())
const confirmBody = (spy) => spy.mock.calls.at(-1)[0]

describe('bands and defaults (K§4)', () => {
  it('uses high >= 0.8, medium 0.5-0.8, low < 0.5', () => {
    expect([0.97, 0.8, 0.79, 0.5, 0.49, 0].map(band)).toEqual(['high', 'high', 'medium', 'medium', 'low', 'low'])
  })

  it('pre-ticks high and medium, leaves low unticked', () => {
    const { container } = render()
    click(byText(container, 'Show 6 more'))
    const pieces = qa(container, '[data-section="pieces"] input[type=checkbox]')
    expect(pieces).toHaveLength(11)
    expect(pieces.every((el) => el.checked)).toBe(true)
    const composers = qa(container, '[data-section="composers"] input[type=checkbox]')
    expect(composers.map((el) => el.checked)).toEqual([true, true, true])
    const techniques = qa(container, '[data-section="techniques"] input[type=checkbox]')
    expect(techniques.map((el) => el.checked)).toEqual([false, false])
  })

  it('labels each checkbox "Link to <target>" and shows the confidence badge and quote', () => {
    const { container } = render()
    const box = byLabel(container, 'Link to Études, Op. 10 · No. 1')
    expect(box.checked).toBe(true)
    const row = box.closest('[data-row]')
    expect(row.textContent).toContain('High')
    expect(row.textContent).toContain('“Synthetic quote from the note body.”')
    expect(byLabel(container, 'Link to Chopin').closest('[data-row]').textContent).toContain('Mentioned 14 times')
    expect(byLabel(container, 'Link to Let the hand fall').closest('[data-row]').textContent).toContain('Low')
  })
})

describe('header, banner, sections, footer (artboard copy)', () => {
  it('renders the header, the banner and the live footer', () => {
    const { container } = render()
    expect(q(container, 'h2').textContent).toBe('Review links and actions')
    expect(container.textContent).toContain(
      'From “2026-10-18 Roy Howat” · 26 suggestions found by searching your library',
    )
    const banner = q(container, '[data-banner]').textContent
    expect(banner).toBe(
      'Nothing is created until you confirm. Unticked items are skipped. Rejected ones won’t be suggested again for this note.',
    )
    // 11 pieces + 3 composers ticked, Debussy left for later, 3 actions.
    expect(q(container, '[data-footer]').textContent).toContain('Creates 14 links · 3 backlog items.')
    expect(q(container, '[data-footer]').textContent).toContain('1 left for later.')
    expect(byText(container, 'Confirm 17')).toBeTruthy()
    expect(byText(container, 'Reject all')).toBeTruthy()
    expect(byText(container, 'Decide later')).toBeTruthy()
  })

  it('desktop section order is pieces, composers, techniques, pick, unresolved, actions', () => {
    const { container } = render()
    const order = qa(container, '[data-section]').map((el) => el.dataset.section)
    expect(order).toEqual(['pieces', 'composers', 'techniques', 'pick', 'unresolved', 'actions'])
    const heads = qa(container, 'h3').map((el) => el.textContent)
    expect(heads).toEqual([
      'Pieces · high11',
      'Composers · medium3',
      'Techniques · low2',
      'Needs your pick1',
      'Not in your library6',
      'Action items3',
    ])
  })

  it('phone and iPad put "Needs your pick" first', () => {
    for (const presentation of ['sheet', 'formsheet']) {
      const { container } = render({ presentation })
      expect(qa(container, '[data-section]').map((el) => el.dataset.section)).toEqual([
        'pick',
        'pieces',
        'composers',
        'techniques',
        'unresolved',
        'actions',
      ])
      cleanup()
    }
  })

  it('shows the short subtitle and banner on the sheet', () => {
    const { container } = render({ presentation: 'sheet' })
    expect(container.textContent).toContain('26 suggestions from “2026-10-18 Roy Howat”')
    expect(q(container, '[data-banner]').textContent).toBe('Nothing is created until you confirm.')
    expect(qa(container, 'h3')[1].textContent).toBe('Pieces · high11 of 11 ticked')
  })

  it('renders the host note', () => {
    const note = 'Roy Howat is kept as text — he isn’t one of your teachers in PT.'
    const { container } = render({ hostNote: note })
    expect(q(container, '[data-host-note]').textContent).toBe(note)
  })

  it('lets the host override strings', () => {
    const { container } = render({
      strings: { title: 'Revisar enlaces', confirm: (n) => `Confirmar ${n}` },
    })
    expect(q(container, 'h2').textContent).toBe('Revisar enlaces')
    expect(byText(container, 'Confirmar 17')).toBeTruthy()
  })
})

describe('Show more and Untick all', () => {
  it('collapses past 5 rows and expands', () => {
    const { container } = render()
    const section = () => q(container, '[data-section="pieces"]')
    expect(qa(section(), '[data-row="link"]')).toHaveLength(5)
    click(byText(section(), 'Show 6 more'))
    expect(qa(section(), '[data-row="link"]')).toHaveLength(11)
    click(byText(section(), 'Show fewer'))
    expect(qa(section(), '[data-row="link"]')).toHaveLength(5)
  })

  it('hidden rows still count and still go to the server', () => {
    const { container, onConfirm } = render()
    click(byText(container, 'Confirm 17'))
    expect(confirmBody(onConfirm).links.filter((l) => l.entity_type !== 'composer')).toHaveLength(11)
  })

  it('Untick all clears a section and becomes Tick all', () => {
    const { container } = render()
    const section = () => q(container, '[data-section="composers"]')
    click(byText(section(), 'Untick all'))
    expect(qa(section(), 'input[type=checkbox]').every((el) => !el.checked)).toBe(true)
    expect(q(container, '[data-footer]').textContent).toContain('Creates 11 links')
    click(byText(section(), 'Tick all'))
    expect(qa(section(), 'input[type=checkbox]').every((el) => el.checked)).toBe(true)
  })
})

describe('reject and undo', () => {
  it('rejects a row, shows the Rejected state and reports it', () => {
    const { container, onConfirm } = render()
    click(byLabel(container, 'Reject link to Études, Op. 10 · No. 1'))
    const row = byLabel(container, 'Link to Études, Op. 10 · No. 1, rejected').closest('[data-row]')
    expect(row.dataset.rejected).toBe('true')
    expect(row.textContent).toContain('Rejected')
    expect(q(container, '[data-footer]').textContent).toContain('Creates 13 links')
    click(byText(container, 'Confirm 16'))
    const body = confirmBody(onConfirm)
    expect(body.rejected).toEqual([{ entity_type: 'movement', entity_id: 1001, anchor: 'op-10-no-1' }])
    expect(body.links.some((l) => l.entity_id === 1001)).toBe(false)
  })

  it('Undo restores the row and its default tick', () => {
    const { container, onConfirm } = render()
    click(byLabel(container, 'Reject link to Études, Op. 10 · No. 1'))
    click(byLabel(container, 'Undo reject link to Études, Op. 10 · No. 1'))
    expect(byLabel(container, 'Link to Études, Op. 10 · No. 1').checked).toBe(true)
    click(byText(container, 'Confirm 17'))
    expect(confirmBody(onConfirm).rejected).toEqual([])
  })

  it('Reject all passes a body that rejects every suggested link', () => {
    const { container, onRejectAll } = render()
    click(byText(container, 'Reject all'))
    const body = onRejectAll.mock.calls[0][0]
    expect(body.links).toEqual([])
    expect(body.action_items).toEqual([])
    // 17 suggested links, with the Debussy item rejecting each of its 4 candidates.
    expect(body.rejected).toHaveLength(16 + 4)
    expect(body.rejected).toContainEqual({ entity_type: 'repertoire', entity_id: 26, anchor: 'debussy' })
    expect(checkShape('ConfirmBody', body).ok).toBe(true)
  })
})

describe('Needs your pick (ambiguous items)', () => {
  const group = (c) => q(c, '[role=radiogroup]')

  it('lists every candidate with #id, plus "None of these — skip"', () => {
    const { container } = render()
    expect(group(container).getAttribute('aria-label')).toBe('Which Préludes, Livre 1')
    const labels = qa(group(container), 'label').map((el) => el.textContent)
    expect(labels).toEqual([
      'Préludes, Livre 1 · #18',
      'Preludes (Book 1) · #19',
      'Préludes (Book 1) · #26',
      'Préludes, Livre 2 · #20',
      'None of these — skip',
    ])
    expect(qa(group(container), 'input[type=radio]').every((el) => !el.checked)).toBe(true)
  })

  it('shows the duplicate_group hint', () => {
    const { container } = render()
    expect(group(container).textContent).toContain(
      'Three look like the same book. You can merge them later in Repertoire.',
    )
  })

  it('leaves an unpicked item in deferred, not in links', () => {
    const { container, onConfirm } = render()
    click(byText(container, 'Confirm 17'))
    const body = confirmBody(onConfirm)
    expect(body.deferred).toEqual([{ mention: 'Synthetic quote from the note body.', anchor: 'debussy' }])
    expect(body.links.some((l) => l.entity_type === 'repertoire' && l.entity_id >= 18 && l.entity_id <= 26)).toBe(false)
  })

  it('links ONE candidate when picked, with that candidate’s confidence', () => {
    const { container, onConfirm } = render()
    click(qa(group(container), 'input[type=radio]')[2])
    expect(q(container, '[data-footer]').textContent).toContain('Creates 15 links')
    expect(q(container, '[data-footer]').textContent).toContain('1 picked.')
    click(byText(container, 'Confirm 18'))
    const body = confirmBody(onConfirm)
    expect(body.deferred).toBeUndefined()
    const picked = body.links.filter((l) => l.anchor === 'debussy')
    expect(picked).toEqual([
      {
        entity_type: 'repertoire',
        entity_id: 26,
        anchor: 'debussy',
        quote: 'Synthetic quote from the note body.',
        proposed_by: 'resolver',
        confidence: 0.53,
      },
    ])
  })

  it('"None of these" skips: not linked and not deferred', () => {
    const { container, onConfirm } = render()
    click(qa(group(container), 'input[type=radio]').at(-1))
    expect(q(container, '[data-footer]').textContent).toContain('1 skipped.')
    click(byText(container, 'Confirm 17'))
    const body = confirmBody(onConfirm)
    expect(body.deferred).toBeUndefined()
    expect(body.links.some((l) => l.anchor === 'debussy')).toBe(false)
    expect(body.rejected.some((r) => r.anchor === 'debussy')).toBe(false)
  })
})

describe('Not in your library and Someday (K§5)', () => {
  it('is read-only without onSomeday: no switches, no blurb, no someday key', () => {
    const { container, onConfirm } = render()
    const section = q(container, '[data-section="unresolved"]')
    expect(qa(section, 'input')).toHaveLength(0)
    expect(section.textContent).not.toContain('someday')
    expect(section.textContent).toContain('Bach WTC book 1 · Bach')
    expect(section.textContent).toContain('Fauré · composer')
    click(byText(container, 'Confirm 17'))
    expect(confirmBody(onConfirm).someday).toBeUndefined()
  })

  it('shows the switches when onSomeday is given and emits someday', () => {
    const onSomeday = vi.fn()
    const { container, onConfirm } = render({ onSomeday })
    const section = q(container, '[data-section="unresolved"]')
    expect(section.textContent).toContain('Switch on to keep one as a “someday” idea.')
    expect(qa(section, 'input[type=checkbox]')).toHaveLength(6)
    click(byLabel(container, 'Save Fauré as someday'))
    expect(onSomeday).toHaveBeenLastCalledWith([{ mention: 'Fauré', kind_hint: 'composer', quote: 'Synthetic quote from the note body.' }])
    expect(q(container, '[data-footer]').textContent).toContain('1 someday idea.')
    click(byText(container, 'Confirm 18'))
    expect(confirmBody(onConfirm).someday).toEqual([
      { mention: 'Fauré', kind_hint: 'composer', quote: 'Synthetic quote from the note body.' },
    ])
    click(byLabel(container, 'Save Fauré as someday'))
    click(byText(container, 'Confirm 17'))
    expect(confirmBody(onConfirm).someday).toBeUndefined()
  })
})

describe('Action items', () => {
  it('pre-ticks every action on its proposed lane and attaches link_index', () => {
    const { container, onConfirm } = render()
    const rows = qa(container, '[data-section="actions"] [data-row="action"]')
    expect(rows).toHaveLength(3)
    expect(rows[0].textContent).toContain('Études, Op. 10 · No. 3')
    expect(rows[1].textContent).toContain('No piece linked')
    click(byText(container, 'Confirm 17'))
    const { action_items, links } = confirmBody(onConfirm)
    expect(action_items.map((a) => a.lane)).toEqual(['practice', 'lesson', 'practice'])
    expect(links[action_items[0].link_index]).toMatchObject({ entity_id: 1003, anchor: 'op-10-no-3' })
    // The pedalling anchor matches no link exactly, so it attaches to the movement’s own link.
    expect(links[action_items[2].link_index]).toMatchObject({ entity_id: 1006 })
    expect(action_items[1].link_index).toBeUndefined()
  })

  it('switches the lane and drops an unticked action', () => {
    const { container, onConfirm } = render()
    const rows = () => qa(container, '[data-section="actions"] [data-row="action"]')
    const second = rows()[1]
    expect(qa(second, 'button').map((b) => b.getAttribute('aria-pressed'))).toEqual(['false', 'true'])
    click(byText(second, 'Practice'))
    expect(qa(rows()[1], 'button').map((b) => b.getAttribute('aria-pressed'))).toEqual(['true', 'false'])
    click(byLabel(container, 'Add action: Mark the pedal changes in the score.'))
    expect(q(container, '[data-footer]').textContent).toContain('2 backlog items')
    click(byText(container, 'Confirm 16'))
    const { action_items } = confirmBody(onConfirm)
    expect(action_items).toHaveLength(2)
    expect(action_items[1]).toMatchObject({ text: 'Bring a clock-like reference recording to the next lesson.', lane: 'practice' })
  })
})

describe('ConfirmBody', () => {
  it('matches the default snapshot and validates against the vendored schema', () => {
    const { container, onConfirm } = render()
    click(byText(container, 'Confirm 17'))
    const body = confirmBody(onConfirm)
    expect(checkShape('ConfirmBody', body).ok).toBe(true)
    expect({
      links: body.links.length,
      first: body.links[0],
      composer: body.links.find((l) => l.entity_type === 'composer'),
      rejected: body.rejected,
      action_items: body.action_items,
      deferred: body.deferred,
      someday: body.someday,
    }).toMatchInlineSnapshot(`
      {
        "action_items": [
          {
            "anchor": "op-10-no-3",
            "entity_id": 1003,
            "entity_type": "movement",
            "lane": "practice",
            "link_index": 1,
            "text": "Play the left hand alone, listening for the line.",
          },
          {
            "lane": "lesson",
            "text": "Bring a clock-like reference recording to the next lesson.",
          },
          {
            "anchor": "pedalling",
            "entity_id": 1006,
            "entity_type": "movement",
            "lane": "practice",
            "link_index": 4,
            "text": "Mark the pedal changes in the score.",
          },
        ],
        "composer": {
          "confidence": 0.78,
          "entity_id": 13,
          "entity_type": "composer",
          "proposed_by": "resolver",
          "quote": "Synthetic quote from the note body.",
        },
        "deferred": [
          {
            "anchor": "debussy",
            "mention": "Synthetic quote from the note body.",
          },
        ],
        "first": {
          "anchor": "op-10-no-1",
          "confidence": 0.96,
          "entity_id": 1001,
          "entity_type": "movement",
          "proposed_by": "resolver",
          "quote": "Synthetic quote from the note body.",
        },
        "links": 14,
        "rejected": [],
        "someday": undefined,
      }
    `)
  })

  it('a complete set of user choices still validates', () => {
    const onSomeday = vi.fn()
    const { container, onConfirm } = render({ onSomeday })
    click(qa(container, '[role=radiogroup] input[type=radio]')[0])
    click(byLabel(container, 'Reject link to Études, Op. 10 · No. 4'))
    click(byLabel(container, 'Save Duparc as someday'))
    click(byLabel(container, 'Link to Pedalling'))
    click(byText(container, 'Confirm 19'))
    expect(checkShape('ConfirmBody', confirmBody(onConfirm)).ok).toBe(true)
  })

  it('model.derive agrees with the component', () => {
    const model = buildModel(proposal())
    const { counts } = derive(model, initialState(model))
    expect(counts).toMatchObject({ links: 14, backlog: 3, someday: 0, confirm: 17, later: 1 })
  })
})

describe('modal behaviour', () => {
  it('Esc is Decide later', () => {
    const { onDecideLater } = render()
    act(() => {
      document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))
    })
    expect(onDecideLater).toHaveBeenCalledTimes(1)
  })

  it('Close, Decide later and the scrim all call onDecideLater and nothing else', () => {
    const { container, onDecideLater, onConfirm, onRejectAll } = render()
    click(byLabel(container, 'Close'))
    click(byText(container, 'Decide later'))
    click(q(container, '[data-arpn="proposal-review"]'))
    expect(onDecideLater).toHaveBeenCalledTimes(3)
    expect(onConfirm).not.toHaveBeenCalled()
    expect(onRejectAll).not.toHaveBeenCalled()
  })

  it('is a labelled modal dialog and focuses into it', () => {
    const { container } = render()
    const dialog = q(container, '[role=dialog]')
    expect(dialog.getAttribute('aria-modal')).toBe('true')
    expect(document.getElementById(dialog.getAttribute('aria-labelledby')).textContent).toBe('Review links and actions')
    expect(document.activeElement).toBe(dialog)
    expect(document.body.style.overflow).toBe('hidden')
  })

  it('traps Tab inside the dialog in both directions', () => {
    const { container } = render()
    const dialog = q(container, '[role=dialog]')
    const items = qa(dialog, 'button, input').filter((el) => !el.disabled)
    const first = items[0]
    const last = items.at(-1)
    last.focus()
    const tab = (shiftKey) => {
      const e = new KeyboardEvent('keydown', { key: 'Tab', shiftKey, bubbles: true, cancelable: true })
      act(() => {
        document.dispatchEvent(e)
      })
      return e
    }
    expect(tab(false).defaultPrevented).toBe(true)
    expect(document.activeElement).toBe(first)
    expect(tab(true).defaultPrevented).toBe(true)
    expect(document.activeElement).toBe(last)
  })

  it('restores focus and page scroll on unmount', () => {
    const opener = document.createElement('button')
    document.body.append(opener)
    opener.focus()
    render()
    expect(document.activeElement).not.toBe(opener)
    cleanup()
    expect(document.activeElement).toBe(opener)
    expect(document.body.style.overflow).toBe('')
    opener.remove()
  })

  it('keyboard paths: Space ticks, arrows move a radio, Enter on Confirm submits', () => {
    const { container, onConfirm } = render()
    const box = byLabel(container, 'Link to Pedalling')
    box.focus()
    click(box) // jsdom turns a Space keypress on a checkbox into a click
    expect(box.checked).toBe(true)
    const confirm = byText(container, 'Confirm 18')
    confirm.focus()
    click(confirm)
    expect(confirmBody(onConfirm).links.some((l) => l.entity_id === 302)).toBe(true)
  })
})

describe('presentation', () => {
  it('maps viewport widths per K§8', () => {
    expect([390, 599, 600, 820, 1023, 1024, 1280].map(presentationForWidth)).toEqual([
      'sheet',
      'sheet',
      'formsheet',
      'formsheet',
      'formsheet',
      'dialog',
      'dialog',
    ])
  })

  it('auto follows window.innerWidth and resizes', () => {
    const original = window.innerWidth
    const setWidth = (w) => {
      Object.defineProperty(window, 'innerWidth', { configurable: true, value: w })
    }
    try {
      setWidth(390)
      const { container } = render({ presentation: 'auto' })
      const root = () => q(container, '[data-arpn="proposal-review"]')
      expect(root().dataset.presentation).toBe('sheet')
      setWidth(820)
      act(() => {
        window.dispatchEvent(new Event('resize'))
      })
      expect(root().dataset.presentation).toBe('formsheet')
      setWidth(1280)
      act(() => {
        window.dispatchEvent(new Event('resize'))
      })
      expect(root().dataset.presentation).toBe('dialog')
    } finally {
      setWidth(original)
    }
  })

  it('an explicit presentation wins over the viewport', () => {
    const { container } = render({ presentation: 'formsheet' })
    expect(q(container, '[data-arpn="proposal-review"]').dataset.presentation).toBe('formsheet')
  })

  it('starts over when a new proposal arrives', () => {
    const calls = { onConfirm: vi.fn(), onDecideLater: vi.fn(), onRejectAll: vi.fn() }
    const container = document.createElement('div')
    document.body.append(container)
    const root = createRoot(container)
    const first = proposal()
    act(() => root.render(h(ProposalReview, { proposal: first, presentation: 'dialog', ...calls })))
    click(byLabel(container, 'Reject link to Études, Op. 10 · No. 1'))
    expect(q(container, '[data-footer]').textContent).toContain('Creates 13 links')
    // The same proposal object keeps the user's choices through a re-render ...
    act(() => root.render(h(ProposalReview, { proposal: first, presentation: 'dialog', ...calls })))
    expect(q(container, '[data-footer]').textContent).toContain('Creates 13 links')
    // ... and a refreshed one starts from its own defaults.
    act(() => root.render(h(ProposalReview, { proposal: proposal(), presentation: 'dialog', ...calls })))
    expect(q(container, '[data-footer]').textContent).toContain('Creates 14 links')
    act(() => root.unmount())
    container.remove()
  })
})

describe('small proposals', () => {
  it('hides empty sections and uses singular counts', () => {
    const small = {
      note_id: 1,
      links: [
        {
          entity_type: 'repertoire',
          entity_id: 5,
          entity_label: 'Nocturne',
          quote: 'q',
          confidence: 0.9,
          proposed_by: 'resolver',
          reason: 'r',
        },
      ],
      action_items: [],
      takeaways: [],
      unresolved: [],
      generated_by: ['resolver'],
      cached: false,
      proposed_at: null,
    }
    const { container } = render({ proposal: small, noteTitle: undefined })
    expect(qa(container, '[data-section]').map((el) => el.dataset.section)).toEqual(['pieces'])
    expect(container.textContent).toContain('1 suggestion found by searching your library')
    expect(q(container, '[data-footer]').textContent).toContain('Creates 1 link · 0 backlog items.')
    expect(byText(container, 'Show 0 more')).toBeUndefined()
  })
})
