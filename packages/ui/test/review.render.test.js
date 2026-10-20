import { createElement as h } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { ProposalReview } from '../src/review/index.js'
import { HOST_NOTE, NOTE_TITLE, howatProposal } from '../demo/fixtures/howat.js'

const render = (props = {}) =>
  renderToStaticMarkup(h(ProposalReview, { proposal: howatProposal, presentation: 'dialog', ...props }))

describe('ProposalReview markup (server render)', () => {
  const html = render({ noteTitle: NOTE_TITLE, hostNote: HOST_NOTE })

  it('is a labelled modal dialog', () => {
    expect(html).toContain('role="dialog"')
    expect(html).toContain('aria-modal="true"')
    expect(html).toMatch(/aria-labelledby="[^"]+"/)
    expect(html).toContain('Review links and actions')
  })

  it('carries the mockup copy verbatim', () => {
    expect(html).toContain('From “2026-10-18 Roy Howat” · 26 suggestions found by searching your library')
    expect(html).toContain('Nothing is created until you confirm.')
    expect(html).toContain('Unticked items are skipped. Rejected ones won’t be suggested again for this note.')
    expect(html).toContain('Three look like the same book. You can merge them later in Repertoire.')
    expect(html).toContain('None of these — skip')
    expect(html).toContain(HOST_NOTE)
  })

  it('orders desktop sections: Pieces, Composers, Techniques | pick, unresolved, actions', () => {
    const order = ['Pieces · high', 'Composers · medium', 'Techniques · low', 'Needs your pick', 'Not in your library', 'Action items']
    const at = order.map((name) => html.indexOf(`<h3>${name}</h3>`))
    expect(at.every((i) => i > 0)).toBe(true)
    expect([...at].sort((a, b) => a - b)).toEqual(at)
  })

  it('puts "Needs your pick" first on phone and iPad', () => {
    for (const presentation of ['sheet', 'formsheet']) {
      const out = render({ presentation })
      expect(out.indexOf('<h3>Needs your pick</h3>')).toBeLessThan(out.indexOf('<h3>Pieces · high</h3>'))
      expect(out).toContain(`data-presentation="${presentation}"`)
    }
  })

  it('labels checkboxes "Link to <target>" and shows confidence badges', () => {
    expect(html).toContain('aria-label="Link to Études, Op.10 · Nº 3"')
    expect(html).toContain('aria-label="Reject link to Études, Op.10 · Nº 3"')
    expect(html).toContain('>High<')
    expect(html).toContain('>Medium<')
    expect(html).toContain('>Low<')
    expect(html).toContain('Mentioned 14 times')
  })

  it('pre-ticks high and medium rows and every action; low is unticked', () => {
    const boxes = html.match(/<input type="checkbox"[^>]*>/g) ?? []
    const isOn = (tag) => /checked=""/.test(tag)
    const links = boxes.filter((b) => b.includes('aria-label="Link to'))
    // Five visible pieces (the rest sit behind "Show 6 more"), three composers, two techniques.
    expect(links).toHaveLength(10)
    expect(links.filter(isOn)).toHaveLength(8)
    expect(links.filter((b) => !isOn(b)).every((b) => /Pedaling|Metronome/.test(b))).toBe(true)
    const actions = boxes.filter((b) => b.includes('aria-label="Add action'))
    expect(actions).toHaveLength(3)
    expect(actions.every(isOn)).toBe(true)
  })

  it('collapses to five rows with "Show 6 more", and offers Untick all', () => {
    expect(html).toContain('Show 6 more')
    expect(html).toContain('Untick all')
  })

  it('shows the live footer and the three buttons', () => {
    expect(html).toContain('Creates 14 links · 3 backlog items.')
    expect(html).toContain('Reject all')
    expect(html).toContain('Decide later')
    expect(html).toContain('Confirm 17')
    expect(html).toContain('Debussy: pick left for later.')
  })

  it('renders radios with #id and the skip option', () => {
    expect(html).toContain('#18')
    expect(html).toContain('#26')
    expect(html).toContain('#19')
    expect(html).toContain('#20')
    expect(html.match(/type="radio"/g)).toHaveLength(5)
  })

  it('has a lane segmented control per action item', () => {
    expect(html.match(/role="group" aria-label="Lane"/g)).toHaveLength(3)
    expect(html).toContain('aria-pressed="true">Practice')
    expect(html).toContain('aria-pressed="true">Lesson')
  })
})

describe('Someday switches (K§5)', () => {
  it('are hidden, and the list read-only, without onSomeday', () => {
    const html = render()
    expect(html).not.toContain('Save WTC Book 1 as someday')
    expect(html).not.toContain('>Someday<')
    expect(html).toContain('<b>WTC Book 1</b>')
    expect(html).not.toContain('0 someday ideas')
  })

  it('appear with onSomeday, and the footer counts them', () => {
    const html = render({ onSomeday: () => {} })
    expect(html).toContain('aria-label="Save WTC Book 1 as someday"')
    expect(html.match(/>Someday</g)).toHaveLength(6)
    expect(html).toContain('0 someday ideas.')
  })
})

describe('strings override', () => {
  it('replaces any key', () => {
    const html = render({ strings: { title: 'Check suggestions', decideLater: 'Later' } })
    expect(html).toContain('Check suggestions')
    expect(html).toContain('>Later<')
  })
})

describe('without a note title', () => {
  it('drops the From clause', () => {
    expect(render()).toContain('26 suggestions found by searching your library')
    expect(render()).not.toContain('From “')
  })
})

describe('an empty proposal', () => {
  it('renders a disabled Confirm', () => {
    const html = render({ proposal: { note_id: 1, links: [], action_items: [], unresolved: [], takeaways: [] } })
    expect(html).toMatch(/<button[^>]*disabled=""[^>]*>Confirm<\/button>/)
  })
})
