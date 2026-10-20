// C6e scenes: the live-preview layer, the editor toolbar and the Live preview | Source toggle, as in the
// EditorDesk / EditorPhone artboards.
//   preview-desk          desk: toolbar with the mode toggle, Live preview on, the caret on the **bold** line
//   preview-source        the same note in Source mode
//   preview-phone         phone bar pinned above a simulated 320 px keyboard, with Hide keyboard
//   preview-link-popover  desk, with the [[ popover opened by the toolbar's Link button
//   preview-images-off    desk on a host that takes no attachments: the Image button is dimmed
// The host here is a mock: a seven-row catalogue behind the scheme callbacks, and images drawn as inline SVG.
// Scenes unmount on hashchange.
import { createElement as h, useEffect, useState } from 'react'
import { flushSync } from 'react-dom'
import { createRoot } from 'react-dom/client'
import { NoteEditor } from '../../src/editor/index.js'
import { EditorToolbar, livePreview, switchPreviewMode } from '../../src/preview/index.js'

const MIB = 1024 * 1024
const CAPS = {
  protocol: 1,
  attachments: true,
  mime_allowlist: ['image/webp', 'image/png', 'application/pdf'],
  limits: { max_attachment_bytes: 25 * MIB, max_note_bytes: 200 * MIB, max_body_chars: 2 * MIB, max_attachments_per_note: 500, manifest_page_size: 50, upload_ticket_ttl_s: 900 },
  kinds: ['masterclass', 'lesson', 'reading', 'reflection', 'note'],
  export: true,
}

const CATALOGUE = [
  { entity_type: 'repertoire', entity_id: 35, entity_label: 'Études, Op.10' },
  { entity_type: 'movement', entity_id: 1003, entity_label: 'Études, Op.10 · Nº 3' },
  { entity_type: 'repertoire', entity_id: 36, entity_label: 'Études, Op.25' },
  { entity_type: 'repertoire', entity_id: 18, entity_label: 'Préludes, Livre 1', composer_label: 'Debussy' },
  { entity_type: 'composer', entity_id: 13, entity_label: 'Chopin' },
  { entity_type: 'composer', entity_id: 7, entity_label: 'Bach' },
]
const fold = (s) => s.normalize('NFD').replace(/\p{M}/gu, '').toLowerCase()
const wait = (ms) => new Promise((r) => setTimeout(r, ms))

const scheme = {
  prefix: 'ex',
  async search(q) {
    await wait(30)
    const needle = fold(q.trim())
    return CATALOGUE.filter((row) => !needle || fold(row.entity_label).includes(needle))
  },
  async resolve(type, id) {
    await wait(30)
    const row = CATALOGUE.find((r) => r.entity_type === type && r.entity_id === id)
    return row ? { title: row.entity_label, url: `/${type}/${id}` } : null
  },
}
const SCHEMES = [scheme]

// A photograph stand-in, as a data: URI so the demo needs no network.
const shot = (label, width, height) =>
  `data:image/svg+xml;utf8,${encodeURIComponent(
    `<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}"><rect width="100%" height="100%" fill="#CBD5E1"/><path d="M0 ${height * 0.8} L${width * 0.3} ${height * 0.45} L${width * 0.55} ${height * 0.7} L${width * 0.75} ${height * 0.5} L${width} ${height * 0.8} V${height} H0 Z" fill="#94A3B8"/><text x="12" y="28" font-family="sans-serif" font-size="16" fill="#0F172A">${label}</text></svg>`,
  )}`

const resolveAttachment = async (ref) => {
  await wait(30)
  if (ref.id === '41') return shot('IMG_2040.png', 480, 270)
  if (ref.target === 'Howat score.png') return shot('Howat score.png', 438, 282)
  return null
}

const BODY = `# Roy Howat masterclass

Played through [@Études, Op.10](ex://repertoire/35), starting with [@Études, Op.10 · Nº 3](ex://movement/1003).

## What he said

He kept returning to **the weight on the first beat** and to *pedal changes*.

![IMG_2040.png](attachment://41)

- Slow practice, hands separate
- Listen for the pedal in bar 12
- \`rit.\` only where marked

> Nº 3 and Nº 12 for next week.

### Score

![[Howat score.png|438x282]]
`
const CARET_AT = BODY.indexOf('the weight') + 4

const css = `
.pv-wrap { display: flex; flex-direction: column; gap: 12px; max-width: 760px; }
.pv-note { margin: 0; font-size: 13px; color: var(--arpn-muted); }
`

function Page({ capabilities = CAPS, toolbar, mode: initialMode = 'preview', onView }) {
  const [view, setView] = useState(null)
  const [mode, setMode] = useState(initialMode)
  const [doc, setDoc] = useState(BODY)
  const [extensions] = useState(() => [livePreview({ resolveAttachment, mode: initialMode })])
  // After the commit that hands the toolbar its view, so a scene can click the bar without a timer.
  useEffect(() => {
    if (view) onView?.(view, setMode)
  }, [view])
  return h(
    'div',
    { className: 'pv-wrap' },
    // 'desk' unless a scene says otherwise: the scenes are about the bar, whatever the viewport.
    h(EditorToolbar, { view, capabilities, mode, onModeChange: setMode, variant: 'desk', ...toolbar }),
    h(NoteEditor, {
      value: doc,
      onChange: setDoc,
      schemes: SCHEMES,
      capabilities,
      upload: () => new Promise(() => {}),
      extensions,
      ariaLabel: 'Note body',
      onReady: setView,
    }),
    h('p', { className: 'pv-note' }, 'Markers dim away from the cursor line; the Markdown underneath is unchanged.'),
  )
}

function mount(container, props, after) {
  const style = document.createElement('style')
  style.textContent = css
  container.append(style)
  const host = document.createElement('div')
  container.append(host)
  const root = createRoot(host)
  flushSync(() => root.render(h(Page, { ...props, onView: (view, setMode) => after?.(host, view, setMode) })))
  const leave = () => {
    window.removeEventListener('hashchange', leave)
    root.unmount()
  }
  window.addEventListener('hashchange', leave)
}

const caretOnBold = (_host, view) => {
  view.dispatch({ selection: { anchor: CARET_AT } })
}

export default [
  { id: 'preview-desk', title: 'Editor preview (desk)', render: (c) => mount(c, {}, caretOnBold) },
  {
    id: 'preview-source',
    title: 'Editor preview (source)',
    render: (c) =>
      mount(c, { mode: 'source' }, (host, view) => {
        switchPreviewMode(view, 'source')
        caretOnBold(host, view)
      }),
  },
  {
    id: 'preview-phone',
    title: 'Editor preview (phone)',
    render: (c) => mount(c, { toolbar: { variant: 'phone', alwaysVisible: true, keyboardHeight: 320 } }, caretOnBold),
  },
  {
    id: 'preview-link-popover',
    title: 'Editor preview ([[ popover)',
    render: (c) =>
      mount(c, {}, (host, view) => {
        view.dispatch({ selection: { anchor: view.state.doc.length } })
        host.querySelector('[data-action=link]')?.click()
      }),
  },
  {
    id: 'preview-images-off',
    title: 'Editor preview (attachments off)',
    render: (c) => mount(c, { capabilities: { ...CAPS, attachments: false, mime_allowlist: null } }, caretOnBold),
  },
]
