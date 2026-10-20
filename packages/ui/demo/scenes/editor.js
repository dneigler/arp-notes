// C6d scenes: NoteEditor + NoteMetaFields + EditorRail, as in the EditorDesk / EditorPhone artboards.
//   editor-desk          the desk layout (editor and rail side by side; stacked under 900 px)
//   editor-autocomplete  desk, with the [[ popover open
//   editor-policy-off    desk on a host that takes no attachments, with the 'Image not added' dialog open
//   editor-uploading     desk, with an image upload held at 62% (editor strip and rail)
// The host here is a mock: a ten-row catalogue behind the scheme callbacks, and an upload that never lands
// by itself. Scenes unmount on hashchange.
import { EditorView } from '@codemirror/view'
import { createElement as h, useState } from 'react'
import { flushSync } from 'react-dom'
import { createRoot } from 'react-dom/client'
import { EditorRail, NoteEditor, NoteMetaFields } from '../../src/editor/index.js'

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
  { entity_type: 'movement', entity_id: 1012, entity_label: 'Études, Op.10 · Nº 12' },
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
    await wait(40)
    const needle = fold(q.trim())
    return CATALOGUE.filter((row) => !needle || fold(row.entity_label).includes(needle))
  },
  async resolve(type, id) {
    await wait(60)
    const row = CATALOGUE.find((r) => r.entity_type === type && r.entity_id === id)
    return row ? { title: row.entity_label, url: `/${type}/${id}` } : null
  },
}

const BODY = `# Masterclass notes

Played through [@Études, Op.10](ex://repertoire/35), starting with [@Études, Op.10 · Nº 3](ex://movement/1003).
He kept returning to [@Chopin](ex://composer/13)’s pedal marks and to [@Lost piece](ex://repertoire/404).

![IMG_2040.png](attachment://41)

- Slow practice, **hands separate**
- Listen for the weight on the first beat ==every time==

> [!note] Homework
> Nº 3 and Nº 12 for next week. See [[Roy Howat]] for the fingering chart.
`

const ATTACHMENTS = [{ blob_id: 41, filename: 'IMG_2040.png', size_bytes: 1.4 * MIB }]

const css = `
.edit-grid { display: grid; grid-template-columns: minmax(0, 1fr) 280px; gap: 24px; align-items: start; max-width: 1100px; }
.edit-main { display: flex; flex-direction: column; gap: 16px; min-width: 0; }
@media (max-width: 900px) { .edit-grid { grid-template-columns: minmax(0, 1fr); } }
`

function Desk({ capabilities, onReady, body = BODY }) {
  const [doc, setDoc] = useState(body)
  const [meta, setMeta] = useState({ title: '2026-10-18 Roy Howat masterclass', kind: 'masterclass', note_date: '2026-10-18' })
  const [status, setStatus] = useState({ uploads: [] })
  const schemes = DESK_SCHEMES
  const upload = (file, { onProgress }) => {
    onReady?.({ file, onProgress })
    return new Promise(() => {}) // held: the scene shows the strip mid-upload
  }
  return h(
    'div',
    { className: 'edit-grid' },
    h(
      'div',
      { className: 'edit-main' },
      h(NoteMetaFields, { ...meta, kinds: capabilities.kinds, onChange: (patch) => setMeta((m) => ({ ...m, ...patch })) }),
      h(NoteEditor, {
        value: doc,
        onChange: setDoc,
        schemes,
        upload,
        capabilities,
        onStatus: setStatus,
        ariaLabel: 'Note body',
        autosave: { save: async (b, v) => ({ note: { version: v + 1 } }), version: 1 },
      }),
    ),
    h(EditorRail, { doc, attachments: ATTACHMENTS, uploads: status.uploads, capabilities, schemes, hrefForEntity: (t, id) => `#/${t}/${id}` }),
  )
}

const DESK_SCHEMES = [scheme]

function mount(container, props, after) {
  const style = document.createElement('style')
  style.textContent = css
  container.append(style)
  const host = document.createElement('div')
  container.append(host)
  const root = createRoot(host)
  let hooks = null
  flushSync(() => root.render(h(Desk, { ...props, onReady: (h2) => (hooks = h2) })))
  const leave = () => {
    window.removeEventListener('hashchange', leave)
    root.unmount()
  }
  window.addEventListener('hashchange', leave)
  if (after) after(host, () => hooks)
}

function editorView(host) {
  // CodeMirror stamps the view on the contentDOM's parent chain; the demo reaches it through the DOM event path.
  return host.querySelector('.cm-content')
}

function paste(host, file) {
  caretToEnd(host)
  const event = new Event('paste', { bubbles: true, cancelable: true })
  event.clipboardData = { files: [file], types: ['Files'], getData: () => '' }
  flushSync(() => editorView(host).dispatchEvent(event))
}

function fakeFile(name, type, size) {
  const f = new File([new Uint8Array(16)], name, { type })
  Object.defineProperty(f, 'size', { value: size })
  return f
}

function caretToEnd(host) {
  const view = EditorView.findFromDOM(host.querySelector('.cm-editor'))
  view.focus()
  view.dispatch({ selection: { anchor: view.state.doc.length } })
}

// Types `text` at the end of the document the way the keyboard does, through CodeMirror's own input path.
function typeInto(host, text) {
  caretToEnd(host)
  const content = editorView(host)
  const range = document.createRange()
  range.selectNodeContents(content)
  range.collapse(false)
  getSelection().removeAllRanges()
  getSelection().addRange(range)
  document.execCommand('insertText', false, text)
}

export default [
  { id: 'editor-desk', title: 'Editor (desk)', render: (c) => mount(c, { capabilities: CAPS }) },
  {
    id: 'editor-autocomplete',
    title: 'Editor ([[ popover)',
    render: (c) => mount(c, { capabilities: CAPS, body: 'Played through ' }, (host) => typeInto(host, '[[etu')),
  },
  {
    id: 'editor-policy-off',
    title: 'Editor (attachments off)',
    render: (c) => mount(c, { capabilities: { ...CAPS, attachments: false, mime_allowlist: null } }, (host) => paste(host, fakeFile('IMG_2041.png', 'image/png', 2.9 * MIB))),
  },
  {
    id: 'editor-uploading',
    title: 'Editor (uploading)',
    render: (c) =>
      mount(c, { capabilities: CAPS }, (host, hooks) => {
        paste(host, fakeFile('IMG_2041.png', 'image/png', 2.9 * MIB))
        flushSync(() => hooks()?.onProgress({ loaded: 1.8 * MIB, total: 2.9 * MIB }))
      }),
  },
]
