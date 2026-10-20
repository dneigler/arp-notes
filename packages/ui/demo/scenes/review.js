// C6c scenes: ProposalReview open over a stand-in note page, in every presentation. The review is
// open from the first frame so the axe pass (light, dark, both system themes) sees the overlay.
// Events the component emits are collected on window.__ARPN_REVIEW__.events for the Playwright specs.
import { createElement as h, useRef, useState } from 'react'
import { createRoot } from 'react-dom/client'
import { ProposalReview } from '../../src/review/index.js'
import { HOST_NOTE, NOTE_TITLE, howatProposal } from '../fixtures/howat.js'

let mounted = null // { root, container }: one review scene at a time

const log = (window.__ARPN_REVIEW__ = { events: [] })

function Page({ presentation, someday, hostNote }) {
  const [open, setOpen] = useState(true)
  const opener = useRef(null)
  const emit = (type, payload) => log.events.push({ type, payload })
  const close = (type) => (payload) => {
    emit(type, payload)
    setOpen(false)
  }
  return h(
    'div',
    { style: { maxWidth: 720, margin: '0 auto', display: 'grid', gap: 12 } },
    h('h1', { style: { margin: 0, fontSize: 28 } }, NOTE_TITLE),
    h('p', { style: { margin: 0, color: 'var(--arpn-muted)' } }, 'Sun 18 Oct 2026 · 25 min · with Roy Howat'),
    h(
      'button',
      {
        id: 'open-review',
        ref: opener,
        type: 'button',
        onClick: () => setOpen(true),
        style: {
          justifySelf: 'start',
          minHeight: 44,
          padding: '0 16px',
          borderRadius: 12,
          border: '1px solid var(--arpn-primary)',
          background: 'var(--arpn-primary)',
          color: 'var(--arpn-on-primary)',
          font: 'inherit',
          fontWeight: 600,
        },
      },
      'Review suggestions',
    ),
    open &&
      h(ProposalReview, {
        proposal: howatProposal,
        presentation,
        noteTitle: NOTE_TITLE,
        hostNote: hostNote ? HOST_NOTE : undefined,
        onConfirm: close('confirm'),
        onDecideLater: () => close('decideLater')(undefined),
        onRejectAll: close('rejectAll'),
        onSomeday: someday ? (mention, enabled) => emit('someday', { mention, enabled }) : undefined,
      }),
  )
}

function scene(id, title, props) {
  return {
    id,
    title,
    render(container) {
      mounted?.root.unmount()
      const host = document.createElement('div')
      container.append(host)
      const root = createRoot(host)
      mounted = { root, container }
      log.events.length = 0
      root.render(h(Page, props))
    },
  }
}

export default [
  scene('review-dialog', 'Review (dialog)', { presentation: 'dialog', someday: true, hostNote: true }),
  scene('review-sheet', 'Review (phone sheet)', { presentation: 'sheet', someday: true, hostNote: true }),
  scene('review-formsheet', 'Review (iPad form sheet)', { presentation: 'formsheet', someday: false, hostNote: false }),
  scene('review-auto', 'Review (auto)', { presentation: 'auto', someday: true, hostNote: true }),
]
