// C6c scenes: ProposalReview on the Roy Howat masterclass proposal (26 suggestions, as in the
// ReviewDesk / ReviewPhone / ReviewTablet artboards).
//   review-desk / review-phone / review-tablet  one presentation each, whatever the viewport
//   review-auto                                 presentation='auto': open it at 390, 820 and 1280 px
//   review-states                               auto, with Someday on and a row rejected, a pick made
//                                               and a section expanded, so axe sees those states too
// The review is a fixed overlay, so a stand-in note page sits behind its scrim.
import { createElement as h } from 'react'
import { flushSync } from 'react-dom'
import { createRoot } from 'react-dom/client'
import { ProposalReview } from '../../src/review/index.js'

const link = (entity_type, entity_id, entity_label, confidence, quote, extra = {}) => ({
  entity_type,
  entity_id,
  entity_label,
  quote,
  confidence,
  proposed_by: 'resolver',
  reason: 'Matched in the library.',
  ...extra,
})

const piece = (n, id, confidence, quote) =>
  link('movement', id, `Études, Op.10 · Nº ${n}`, confidence, quote, { anchor: `op-10-no-${n}` })

const candidate = (entity_id, entity_label, confidence, duplicate_group) => ({
  entity_type: entity_id >= 18 ? 'repertoire' : 'composer',
  entity_id,
  entity_label,
  confidence,
  ...(duplicate_group ? { duplicate_group } : null),
})

const proposal = {
  note_id: 7,
  generated_by: ['resolver'],
  cached: false,
  proposed_at: '2026-10-18T14:30:00',
  takeaways: [],
  links: [
    piece(3, 1003, 0.95, 'So Op. 10 nº 3 is meant to be an operatic piece'),
    piece(12, 1012, 0.93, 'If you practice Nº 12 the wrong way, it will teach you the wrong thing'),
    piece(5, 1005, 0.91, 'Op. 10 nº 5 - why the differences? Leggieriss.'),
    link('movement', 2001, 'Etudes Op.25 · Nº 1', 0.9, 'Op.25 No 1 — Decided to use different note size heads'),
    link('movement', 3001, 'In the Mists · II', 0.88, 'And second movement of Janacek’s In The Mists has a notehead diff'),
    piece(1, 1001, 0.87, 'Etude Op 10 Nº 1 and Nº 8 as optional nocturnes'),
    piece(8, 1008, 0.86, 'Nº 8 is the one to start the lesson with'),
    piece(10, 1010, 0.85, 'Nº 10 — keep the left hand light'),
    piece(6, 1006, 0.84, 'Etude Op 10 Nº 6 and Nº 3 as optional nocturnes you can play'),
    link('repertoire', 35, 'Études, Op.10', 0.97, 'the whole Op. 10 set', { anchor: 'op-10' }),
    link('movement', 2006, 'Etudes Op.25 · Nº 6', 0.82, 'Op.25 Nº 6, the thirds'),
    link('composer', 13, 'Chopin', 0.78, 'Chopin did not always pedal the same way', { mention_count: 14 }),
    link('composer', 21, 'Beethoven', 0.66, 'He must have been listening to Beethoven, not just early Beethoven'),
    link('composer', 7, 'Bach', 0.62, 'the Bach preludes as warm-ups', {
      candidates: [candidate(7, 'Bach', 0.62, 'composer:bach'), candidate(11, 'J. S. Bach', 0.6, 'composer:bach')],
    }),
    link('technique', 301, 'Pedaling', 0.42, 'Pedaling - Chopin didn’t always pedal the same way in the same piece'),
    link('technique', 302, 'Metronome practice', 0.38, 'said to practice with a metronome to get rhythmic steadiness'),
    link('repertoire', 18, 'Préludes, Livre 1', 0.55, 'Debussy preludes - one of them has this', {
      anchor: 'debussy',
      candidates: [
        candidate(18, 'Préludes, Livre 1', 0.55, 'repertoire:preludes-book-1'),
        candidate(26, 'Préludes (Book 1)', 0.53, 'repertoire:preludes-book-1'),
        candidate(19, 'Preludes (Book 1)', 0.54, 'repertoire:preludes-book-1'),
        candidate(20, 'Preludes, Book 2', 0.31),
      ],
    }),
  ],
  unresolved: [
    { mention: 'WTC Book 1', kind_hint: 'work', composer_label: 'WTC Book 1 · Bach', quote: 'WTC Book 1', candidates: [] },
    { mention: 'E Major Nocturne', kind_hint: 'work', composer_label: 'Nocturne · Chopin', quote: 'the E major nocturne', candidates: [] },
    { mention: 'Op 27 Nº 2', kind_hint: 'work', composer_label: 'Nocturne · Chopin', quote: 'Op 27 Nº 2', candidates: [] },
    { mention: 'Op. 55 nº 2', kind_hint: 'work', composer_label: 'Nocturne · Chopin', quote: 'Op. 55 nº 2', candidates: [] },
    { mention: 'Fauré', kind_hint: 'composer', quote: 'Fauré', candidates: [] },
    { mention: 'Duparc', kind_hint: 'composer', quote: '“Dupac” in the note', candidates: [] },
  ],
  action_items: [
    { text: 'Practice Nº 12 slowly — drop the hand', anchor: 'op-10-no-12', entity_type: 'movement', entity_id: 1012, lane: 'practice', proposed_by: 'resolver' },
    { text: 'Always try Chopin’s pedalings first', anchor: 'op-10', entity_type: 'repertoire', entity_id: 35, lane: 'practice', proposed_by: 'resolver' },
    { text: 'Reference Op. 55 nº 2 for the clock', lane: 'lesson', proposed_by: 'resolver' },
  ],
}

const HOST_NOTE = 'Roy Howat is kept as text — he isn’t one of your teachers in PT.'

function backdrop(container) {
  const page = document.createElement('div')
  page.setAttribute('aria-hidden', 'true')
  page.inert = true
  page.style.cssText = 'padding:8px 0;display:flex;flex-direction:column;gap:12px;max-width:800px'
  const title = document.createElement('div')
  title.style.cssText = 'font-size:28px;font-weight:700'
  title.textContent = '2026-10-18 Roy Howat'
  page.append(title)
  for (const w of ['70%', '82%', '60%']) {
    const bar = document.createElement('div')
    bar.style.cssText = `height:14px;width:${w};background:var(--arpn-surface);border-radius:6px`
    page.append(bar)
  }
  container.append(page)
}

function mountReview(container, props, after) {
  backdrop(container)
  const host = document.createElement('div')
  container.append(host)
  const root = createRoot(host)
  const noop = () => {}
  flushSync(() =>
    root.render(
      h(ProposalReview, {
        proposal,
        noteTitle: '2026-10-18 Roy Howat',
        hostNote: HOST_NOTE,
        onConfirm: noop,
        onDecideLater: noop,
        onRejectAll: noop,
        ...props,
      }),
    ),
  )
  if (after) after(host)
  // The review listens on the document and locks page scroll, so leaving the scene unmounts it.
  const leave = () => {
    window.removeEventListener('hashchange', leave)
    root.unmount()
  }
  window.addEventListener('hashchange', leave)
}

const click = (host, find) => flushSync(() => find(host)?.click())
const button = (text) => (host) => [...host.querySelectorAll('button')].find((b) => b.textContent.trim() === text)
const labelled = (label) => (host) => host.querySelector(`[aria-label="${label}"]`)

function openStates(host) {
  click(host, button('Show 6 more'))
  click(host, labelled('Reject link to Études, Op.10 · Nº 8'))
  click(host, (el) => el.querySelectorAll('[role=radiogroup]')[1]?.querySelectorAll('input[type=radio]')[1])
  click(host, labelled('Save Fauré as someday'))
}

export default [
  { id: 'review-desk', title: 'Review (dialog)', render: (c) => mountReview(c, { presentation: 'dialog' }) },
  { id: 'review-phone', title: 'Review (sheet)', render: (c) => mountReview(c, { presentation: 'sheet' }) },
  { id: 'review-tablet', title: 'Review (form sheet)', render: (c) => mountReview(c, { presentation: 'formsheet' }) },
  { id: 'review-auto', title: 'Review (auto)', render: (c) => mountReview(c, { presentation: 'auto' }) },
  {
    id: 'review-states',
    title: 'Review (states)',
    render: (c) => mountReview(c, { presentation: 'auto', onSomeday: () => {} }, openStates),
  },
]
