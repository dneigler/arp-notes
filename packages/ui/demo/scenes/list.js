// C6b scenes: the Ada Keller notes from the Main, ListPhone, NoteDesk, NotePhone, DayDesk, DayPhone and
// TodayDesk artboards. Layouts are pinned (layout='desktop' | 'phone'), so a scene looks the same in
// any viewport; the e2e spec also resizes the window for the auto layout.
//   list-desk / list-phone / list-auto / list-empty   NotesList pinned desktop, pinned phone, sized by its own width; then its empty state
//   list-menu-kind / list-menu-source            phone filter menus open (overlays)
//   note-desk / note-phone                       NoteDetailHeader + NoteRail for an imported note
//   note-deleted / note-delete-confirm           the "Source deleted" state, then its confirm dialog open
//   note-written / note-claude                   a written-here note and a note written by Claude
//   day-desk / day-phone / today-desk / today-phone / feed   NoteCard variants
import { createElement as h } from 'react'
import { flushSync } from 'react-dom'
import { createRoot } from 'react-dom/client'
import { NoteCard, NoteDetailHeader, NoteRail, NotesList } from '../../src/list/index.js'

const NOW = Date.parse('2026-10-20T14:30:00Z')
const noop = () => {}

function shot(label, bg) {
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="320" height="240"><rect width="320" height="240" fill="${bg}"/><text x="160" y="125" text-anchor="middle" font-family="sans-serif" font-size="20" fill="#111">${label}</text></svg>`
  return `data:image/svg+xml;utf8,${encodeURIComponent(svg)}`
}
const SHOTS = ['#E4E4E7', '#D4D4D8', '#CBD5E1', '#E2E8F0', '#D6D3D1', '#E7E5E4']

const attachment = (id, size = 92_000) => ({
  id,
  blob_id: id,
  filename: `1792329${id}.webp`,
  ref_in_markdown: `![[1792329${id}.webp]]`,
  mime: 'image/webp',
  size_bytes: size,
  sha256: String(id).padStart(64, '0'),
  content_url: shot(`image ${id}`, SHOTS[id % SHOTS.length]),
})
const IMAGES = Array.from({ length: 15 }, (_, i) => attachment(i + 1, 89_000))

const TOP = [
  { entity_type: 'repertoire', entity_id: 35, entity_label: 'Études, Op.10' },
  { entity_type: 'repertoire', entity_id: 36, entity_label: 'Etudes Op.25' },
  { entity_type: 'repertoire', entity_id: 37, entity_label: 'In the Mists' },
  { entity_type: 'composer', entity_id: 13, entity_label: 'Chopin' },
]

const howat = {
  id: 1,
  kind: 'masterclass',
  title: '2026-10-18 Ada Keller',
  person: 'Ada Keller',
  note_date: '2026-10-18',
  origin: 'source',
  source_system: 'obsidian',
  source_workspace: 'ExampleVault',
  source_path: 'One on one meetings/2026-10-18 Ada Keller.md',
  last_synced_at: '2026-10-18T11:05:00',
  deleted_at: null,
  link_count: 14,
  attachment_count: 15,
  updated_at: '2026-10-18T11:05:00',
  thumbnail_url: shot('thumb', SHOTS[0]),
  top_links: TOP,
  action_count: 3,
  review_pending: 1,
  duration_min: 25,
}
const written = {
  ...howat,
  id: 2,
  kind: 'reflection',
  title: 'Op. 10 nº 3 — after Keller',
  person: null,
  note_date: '2026-10-19',
  origin: 'app',
  source_system: null,
  source_workspace: null,
  source_path: null,
  last_synced_at: null,
  link_count: 2,
  attachment_count: 2,
  updated_at: '2026-10-19T09:00:00',
  thumbnail_url: shot('thumb', SHOTS[1]),
  top_links: [
    { entity_type: 'movement', entity_id: 1003, entity_label: 'Études, Op.10 · Nº 3' },
    { entity_type: 'movement', entity_id: 3002, entity_label: 'In the Mists · II' },
  ],
  action_count: 0,
  review_pending: 0,
  duration_min: null,
}
const claude = {
  ...written,
  id: 3,
  kind: 'note',
  title: 'Keller on metronome marks',
  source_system: 'llm',
  created_at: '2026-10-19T09:00:00',
  attachment_count: 0,
  thumbnail_url: null,
  link_count: 2,
  top_links: [
    { entity_type: 'movement', entity_id: 2001, entity_label: 'Etudes Op.25 · Nº 1' },
    { entity_type: 'composer', entity_id: 13, entity_label: 'Chopin' },
  ],
}
const blank = {
  ...howat,
  id: 4,
  kind: 'note',
  person: null,
  note_date: null,
  source_path: '2026-10-18 Ada Keller 2.md',
  last_synced_at: '2026-10-18T14:30:00',
  link_count: 0,
  attachment_count: 0,
  thumbnail_url: null,
  top_links: [],
  action_count: 0,
  review_pending: 0,
  duration_min: null,
}
const ITEMS = [howat, written, claude, blank]
const SYNC_SOURCES = [{ source_system: 'obsidian', source_workspace: 'ExampleVault', last_synced_at: '2026-10-18T14:30:00', note_count: 4 }]

const link = (id, entity_type, entity_id, entity_label, extra = {}) => ({
  id,
  entity_type,
  entity_id,
  entity_label,
  status: 'confirmed',
  action_completed: 0,
  sort_order: id,
  ...extra,
})

const note = {
  ...howat,
  body_md: '',
  frontmatter: { arp_id: '5b2f6c1e', 'creation date': '2026-10-18 09:03', tags: 'MeetingNote', 'meeting-date': '2026-10-18', duration: '25' },
  source_url: 'obsidian://open?vault=ExampleVault&file=2026-10-18%20Ada%20Keller',
  version: 3,
  attachments: IMAGES,
  links: [
    link(1, 'repertoire', 35, 'Études, Op.10'),
    ...[1, 3, 5, 6, 8, 10, 12].map((n, i) => link(10 + i, 'movement', 1000 + n, `Études, Op.10 · Nº ${n}`)),
    link(20, 'repertoire', 36, 'Etudes Op.25'),
    link(21, 'movement', 2001, 'Etudes Op.25 · Nº 1'),
    link(22, 'movement', 2006, 'Etudes Op.25 · Nº 6'),
    link(30, 'movement', 3002, 'In the Mists · II'),
    link(40, 'composer', 13, 'Chopin'),
    link(41, 'composer', 21, 'Beethoven'),
    link(42, 'composer', 7, 'Bach'),
    link(50, 'movement', 1012, 'Études, Op.10 · Nº 12', { action_item: 'Practice Op.10 Nº 12 slowly — drop the hand', lane: 'practice' }),
    link(51, 'repertoire', 35, 'Études, Op.10', { action_item: 'Try Chopin’s pedallings in Op.10 first', lane: 'practice' }),
    link(52, 'composer', 13, 'Chopin', { action_item: 'Reference Op. 55 nº 2 for the clock', lane: 'lesson' }),
  ],
}
const deletedNote = {
  ...note,
  deleted_at: '2026-10-20T09:00:00',
  review_pending: 0,
  attachments: [],
  links: note.links.slice(0, 14),
}

const BODY = [
  'training session with Ada Keller',
  'Chopin used words “speaking music”; one student was Viennese.',
  'So Op. 10 nº 3 is meant to be an operatic piece.',
]

// Stand-in for the note body (NoteBody is C6a's): a heading and a short list.
const standIn = (body) =>
  h(
    'article',
    { style: { fontSize: 15, lineHeight: 1.65, color: 'var(--arpn-fg)', flex: 1, minWidth: 0, maxWidth: 720 } },
    h('h2', { style: { fontSize: 22, margin: '12px 0 6px' } }, 'Ada Keller'),
    h('ul', null, body.map((line) => h('li', { key: line }, line))),
  )

/** Mounts `element` in `container`, then runs `after(host)`; unmounts when the scene is left. */
function mountElement(container, element, { width, after } = {}) {
  const host = document.createElement('div')
  if (width) host.style.cssText = `max-width:${width}px`
  container.append(host)
  const root = createRoot(host)
  flushSync(() => root.render(element))
  if (after) after(host)
  const leave = () => {
    window.removeEventListener('hashchange', leave)
    root.unmount()
  }
  window.addEventListener('hashchange', leave)
}

// Focus first, as a keyboard or mouse user would, so an overlay has something to hand focus back to.
const click = (host, find) =>
  flushSync(() => {
    const el = find(host)
    el?.focus()
    el?.click()
  })
const buttonText = (text) => (host) => [...host.querySelectorAll('button')].find((b) => b.textContent.trim() === text)

const listProps = { items: ITEMS, syncSources: SYNC_SOURCES, hostName: 'Practice Tracker', now: NOW, hrefForNote: (id) => `#/notes/${id}`, onNew: noop, onFiltersChange: noop }

const listScene = (id, title, props, opts) => ({
  id,
  title,
  render: (c) => mountElement(c, h(NotesList, { ...listProps, ...props }), opts),
})

// A note page: header, body stand-in, rail. On desktop the rail sits beside the body; on a phone below it.
function notePage(noteData, { phone, headerProps, hostName }) {
  const layout = phone ? 'phone' : 'desktop'
  const body = standIn(BODY)
  const rail = h(NoteRail, { note: noteData, hrefForEntity: (type, id) => `#/${type}/${id}` })
  return h(
    'main',
    { style: { display: 'flex', flexDirection: 'column', gap: 16 } },
    h(NoteDetailHeader, {
      note: noteData,
      capabilities: { export: true },
      onReview: noop,
      onExport: noop,
      onKeepCopy: noop,
      onDeleteFromHost: noop,
      hostName,
      layout,
      now: NOW,
      timeZone: 'UTC',
      ...headerProps,
    }),
    h('div', { style: { display: 'flex', flexDirection: phone ? 'column' : 'row', gap: 32, alignItems: 'flex-start' } }, body, phone ? rail : h('div', { style: { width: 320, flex: 'none' } }, rail)),
  )
}

const cardProps = {
  summary: howat,
  excerpt:
    'Chopin used words "speaking music" … What is Chopin trying to teach in these pieces? Its much more than playing the piano smoothly. So Op. 10 nº 3 is meant to be an operatic piece.',
  images: IMAGES.slice(0, 4),
  imageCount: 15,
  hrefForNote: (id) => `#/notes/${id}`,
  hrefForEntity: (type, id) => `#/${type}/${id}`,
  now: NOW,
  timeZone: 'UTC',
}

export default [
  listScene('list-desk', 'Notes list (desktop)', { layout: 'desktop' }),
  listScene('list-phone', 'Notes list (phone)', { layout: 'phone' }, { width: 390 }),
  listScene('list-auto', 'Notes list (auto layout)', {}),
  listScene('list-empty', 'Notes list (empty)', { layout: 'phone', items: [], syncSources: [], howSyncingHref: '#/help/syncing' }, { width: 390 }),
  listScene('list-menu-kind', 'Notes list (Kind menu)', { layout: 'phone' }, { width: 390, after: (host) => click(host, buttonText('Kind')) }),
  listScene('list-menu-source', 'Notes list (Source menu)', { layout: 'phone' }, { width: 390, after: (host) => click(host, buttonText('Source')) }),

  { id: 'note-desk', title: 'Note (desktop)', render: (c) => mountElement(c, notePage(note, { phone: false, hostName: 'Practice Tracker' })) },
  { id: 'note-phone', title: 'Note (phone)', render: (c) => mountElement(c, notePage(note, { phone: true, hostName: 'PT' }), { width: 390 }) },
  { id: 'note-deleted', title: 'Note (source deleted)', render: (c) => mountElement(c, notePage(deletedNote, { phone: true, hostName: 'PT' }), { width: 390 }) },
  {
    id: 'note-deleted-desk',
    title: 'Note (source deleted, desktop)',
    render: (c) => mountElement(c, notePage(deletedNote, { phone: false, hostName: 'Practice Tracker' })),
  },
  {
    id: 'note-delete-confirm',
    title: 'Note (delete confirm open)',
    render: (c) => mountElement(c, notePage(deletedNote, { phone: true, hostName: 'PT' }), { width: 390, after: (host) => click(host, buttonText('Delete from PT…')) }),
  },
  {
    id: 'note-written',
    title: 'Note (written here)',
    render: (c) => mountElement(c, notePage({ ...note, origin: 'app', source_system: null, source_workspace: null, source_path: null, source_url: null, kind: 'reflection', review_pending: 0 }, { phone: false, hostName: 'Practice Tracker' })),
  },
  {
    id: 'note-claude',
    title: 'Note (written by Claude)',
    render: (c) =>
      mountElement(c, notePage({ ...note, origin: 'app', source_system: 'llm', created_at: '2026-10-19T09:00:00', source_workspace: null, source_path: null, source_url: null, kind: 'note', review_pending: 0, attachments: [] }, { phone: false, hostName: 'Practice Tracker' })),
  },

  { id: 'note-auto', title: 'Note (auto layout)', render: (c) => mountElement(c, notePage(note, { phone: false, hostName: 'Practice Tracker', headerProps: { layout: 'auto' } })) },
  { id: 'day-desk', title: 'Note card (Day, desktop)', render: (c) => mountElement(c, h(NoteCard, { ...cardProps, layout: 'desktop' }), { width: 720 }) },
  { id: 'day-phone', title: 'Note card (Day, phone)', render: (c) => mountElement(c, h(NoteCard, { ...cardProps, layout: 'phone' }), { width: 358 }) },
  {
    id: 'today-desk',
    title: 'Note card (Today, desktop)',
    render: (c) => mountElement(c, h(NoteCard, { ...cardProps, variant: 'today', summary: { ...howat, review_pending: 26 }, images: IMAGES.slice(0, 3), layout: 'desktop' }), { width: 560 }),
  },
  {
    id: 'today-phone',
    title: 'Note card (Today, phone)',
    render: (c) => mountElement(c, h(NoteCard, { ...cardProps, variant: 'today', summary: { ...howat, review_pending: 26 }, layout: 'phone' }), { width: 220 }),
  },
  { id: 'feed', title: 'Note card (feed)', render: (c) => mountElement(c, h(NoteCard, { ...cardProps, variant: 'feed', layout: 'desktop' }), { width: 720 }) },
]
