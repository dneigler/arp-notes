// @vitest-environment jsdom
// C6b: NotesList, NoteCard, NoteDetailHeader, NoteRail. Copy is asserted against the artboards
// (Main, ListPhone, NoteDesk, NotePhone, DayDesk, DayPhone, TodayDesk); data comes from the schema examples.
import { afterEach, describe, expect, it, vi } from 'vitest'
import { checkShape } from '../src/api/validate.js'
import { NoteCard, NoteDetailHeader, NoteRail, NotesList, filtersToParams, groupLinks, partsSummary } from '../src/list/index.js'
import { EMPTY_FILTERS } from '../src/list/NotesList.jsx'
import { durationMinutes, formatNoteDate, monthKey, relativeTime } from '../src/list/format.js'
import { act, cleanup, example, h, mount } from './helpers.js'

afterEach(() => {
  cleanup()
  document.body.style.overflow = ''
})

const NOW = Date.parse('2026-10-20T14:30:00Z')
const q = (c, sel) => c.querySelector(sel)
const qa = (c, sel) => [...c.querySelectorAll(sel)]
// Visible text with a space at every element boundary, so 'Synced 2 days ago' + '·' + 'Open in' reads as prose.
const flat = (node) => (node.nodeType === 3 ? node.data : `${[...node.childNodes].map(flat).join('')} `)
const text = (el) => (el ? flat(el).replace(/\s+/g, ' ').trim() : undefined)
const click = (el) => act(() => el.click())
const buttonByText = (c, t) => qa(c, 'button').find((b) => text(b) === t)
const change = (el, value) =>
  act(() => {
    const proto = el.tagName === 'SELECT' ? HTMLSelectElement.prototype : HTMLInputElement.prototype
    Object.getOwnPropertyDescriptor(proto, 'value').set.call(el, value)
    el.dispatchEvent(new Event(el.tagName === 'SELECT' ? 'change' : 'input', { bubbles: true }))
  })
const keydown = (el, key) => act(() => void el.dispatchEvent(new KeyboardEvent('keydown', { key, bubbles: true, cancelable: true })))

const summary = (over = {}) => ({ ...example('NoteSummary'), ...over })
const note = (over = {}) => ({ ...example('Note'), ...over })

// The five rows of the Main artboard.
const howat = summary({
  id: 1,
  title: '2026-10-18 Ada Keller',
  person: 'Ada Keller',
  note_date: '2026-10-18',
  source_workspace: 'ExampleVault',
  source_path: 'One on one meetings/2026-10-18 Ada Keller.md',
  last_synced_at: '2026-10-18T14:30:00',
  updated_at: '2026-10-18T14:30:00',
  link_count: 14,
  attachment_count: 15,
  action_count: 3,
  review_pending: 1,
  duration_min: 25,
  thumbnail_url: 'https://notes.example.test/t1.webp',
  top_links: [
    { entity_type: 'repertoire', entity_id: 35, entity_label: 'Études, Op.10' },
    { entity_type: 'repertoire', entity_id: 36, entity_label: 'Etudes Op.25' },
    { entity_type: 'repertoire', entity_id: 37, entity_label: 'In the Mists' },
    { entity_type: 'composer', entity_id: 13, entity_label: 'Chopin' },
  ],
})
const written = summary({
  id: 2,
  title: 'Op. 10 nº 3 — after Keller',
  kind: 'reflection',
  person: null,
  note_date: '2026-10-19',
  origin: 'app',
  source_system: null,
  source_workspace: null,
  source_path: null,
  last_synced_at: null,
  updated_at: '2026-10-19T09:00:00',
  link_count: 2,
  attachment_count: 2,
  action_count: 0,
  review_pending: 0,
  duration_min: null,
  thumbnail_url: 'https://notes.example.test/t2.webp',
  top_links: [
    { entity_type: 'movement', entity_id: 1003, entity_label: 'Études, Op.10 · Nº 3' },
    { entity_type: 'movement', entity_id: 3002, entity_label: 'In the Mists · II' },
  ],
})
const claude = summary({
  id: 3,
  title: 'Keller on metronome marks',
  kind: 'note',
  person: null,
  note_date: '2026-10-19',
  origin: 'app',
  source_system: 'llm',
  source_workspace: null,
  source_path: null,
  last_synced_at: null,
  created_at: '2026-10-19T09:00:00',
  updated_at: '2026-10-19T09:00:00',
  link_count: 2,
  attachment_count: 0,
  action_count: 0,
  review_pending: 0,
  duration_min: null,
  thumbnail_url: null,
  top_links: [{ entity_type: 'movement', entity_id: 2001, entity_label: 'Etudes Op.25 · Nº 1' }],
})
const empty = summary({
  id: 4,
  title: '2026-10-18 Ada Keller',
  kind: 'note',
  person: null,
  note_date: null,
  source_workspace: 'ExampleVault',
  source_path: '2026-10-18 Ada Keller 2.md',
  last_synced_at: '2026-10-18T14:30:00',
  updated_at: '2026-10-18T14:30:00',
  link_count: 0,
  attachment_count: 0,
  action_count: 0,
  review_pending: 0,
  duration_min: null,
  thumbnail_url: null,
  top_links: [],
})
const SYNC_SOURCES = [{ source_system: 'obsidian', source_workspace: 'ExampleVault', last_synced_at: '2026-10-18T14:30:00', note_count: 4 }]

function list(props = {}) {
  return mount(
    h(NotesList, {
      items: [howat, written, claude, empty],
      syncSources: SYNC_SOURCES,
      now: NOW,
      layout: 'desktop',
      hrefForNote: (id) => `/notes/${id}`,
      ...props,
    }),
  )
}

describe('formatting helpers', () => {
  it('reads calendar dates without shifting zones', () => {
    expect(formatNoteDate('2026-10-18')).toBe('Sun 18 Oct 2026')
    expect(monthKey({ note_date: '2026-10-31', updated_at: '2026-11-02T00:00:00' })).toBe('2026-10')
    expect(monthKey({ note_date: null, updated_at: '2026-11-02T00:00:00' })).toBe('2026-11')
  })

  it('says how long ago, in the units the mockups use', () => {
    const at = (iso) => relativeTime(iso, NOW)
    expect(at('2026-10-18T14:30:00')).toBe('2 days ago')
    expect(at('2026-10-19T14:30:00')).toBe('1 day ago')
    expect(at('2026-10-20T13:30:00')).toBe('1 hour ago')
    expect(at('2026-10-20T14:29:50')).toBe('just now')
    expect(at(null)).toBe('')
  })

  it('takes the duration from the summary, else a whole-number frontmatter value', () => {
    expect(durationMinutes({ duration_min: 25 })).toBe(25)
    expect(durationMinutes({ frontmatter: { duration: '25' } })).toBe(25)
    expect(durationMinutes({ frontmatter: { duration: '25m' } })).toBeNull()
    expect(durationMinutes({})).toBeNull()
  })
})

describe('NotesList (Main, ListPhone)', () => {
  it('groups rows under a month header and shows the sync line', () => {
    const c = list()
    expect(text(q(c, 'h2'))).toBe('October 2026 · 4 notes')
    expect(text(q(c, '[data-sync-line]'))).toBe('Last sync · Obsidian “ExampleVault” · 2 days ago')
    expect(qa(c, 'li[data-note-id]').map((li) => li.dataset.noteId)).toEqual(['1', '2', '3', '4'])
    expect(q(c, 'li[data-note-id="1"] a').getAttribute('href')).toBe('/notes/1')
  })

  it('draws the imported row like the artboard', () => {
    const row = q(list(), 'li[data-note-id="1"]')
    const t = text(row)
    expect(t).toContain('2026-10-18 Ada Keller')
    expect(t).toContain('Imported · Obsidian')
    expect(t).toContain('1 to review')
    expect(t).toContain('Masterclass · Ada Keller · Sun 18 Oct 2026 · 25 min · One on one meetings/')
    expect(t).toContain('Études, Op.10')
    expect(t).toContain('+10 links · 3 actions · 15 images')
    expect(t).toContain('Synced 2 days ago')
    expect(q(row, '[data-origin="source"] svg')).not.toBeNull()
    expect(q(row, 'img').getAttribute('src')).toBe('https://notes.example.test/t1.webp')
  })

  it('labels written-here and Claude rows, and the empty import', () => {
    const c = list()
    const mine = text(q(c, 'li[data-note-id="2"]'))
    expect(mine).toContain('Written here')
    expect(mine).toContain('Reflection · Mon 19 Oct 2026')
    expect(mine).toContain('2 images')
    expect(mine).toContain('Edited 1 day ago')
    const llm = text(q(c, 'li[data-note-id="3"]'))
    expect(llm).toContain('Claude · via MCP')
    expect(llm).toContain('written by Claude at your request')
    expect(llm).toContain('Created 1 day ago')
    const blank = q(c, 'li[data-note-id="4"]')
    expect(q(blank, '[data-thumb="empty"]').textContent).toBe('Empty')
    expect(text(blank)).toContain('Note · vault root')
    expect(q(c, 'li[data-note-id="1"] [data-thumb="empty"]')).toBeNull()
  })

  it('marks a deleted source row', () => {
    const c = list({ items: [{ ...howat, deleted_at: '2026-10-20T08:00:00' }] })
    expect(text(q(c, 'li'))).toContain('Source deleted')
  })

  it('edits the filters through onFiltersChange without owning them', () => {
    const onFiltersChange = vi.fn()
    const c = list({ onFiltersChange })
    change(q(c, 'input[type=search]'), 'howat')
    expect(onFiltersChange).toHaveBeenLastCalledWith({ ...EMPTY_FILTERS, q: 'howat' })
    click(buttonByText(c, 'Imported'))
    expect(onFiltersChange).toHaveBeenLastCalledWith({ ...EMPTY_FILTERS, origin: 'source' })
    change(qa(c, 'select')[0], 'masterclass')
    expect(onFiltersChange).toHaveBeenLastCalledWith({ ...EMPTY_FILTERS, kind: 'masterclass' })
    change(qa(c, 'select')[1], 'llm')
    expect(onFiltersChange).toHaveBeenLastCalledWith({ ...EMPTY_FILTERS, source: 'llm' })
    click(q(c, 'input[type=checkbox]'))
    expect(onFiltersChange).toHaveBeenLastCalledWith({ ...EMPTY_FILTERS, includeDeleted: true })
  })

  it('shows the filters it was given, the eight kinds and the host in the Source menu', () => {
    const c = list({ filters: { origin: 'app', kind: 'reflection' }, hostName: 'Practice Tracker' })
    expect(buttonByText(c, 'Written here').getAttribute('aria-pressed')).toBe('true')
    expect(buttonByText(c, 'All').getAttribute('aria-pressed')).toBe('false')
    const [kind, source] = qa(c, 'select')
    expect(kind.value).toBe('reflection')
    expect([...kind.options].map((o) => o.textContent)).toEqual(['All kinds', 'Masterclass', 'Workshop', 'Lecture', 'Reading', 'Video', 'Reflection', 'Meeting', 'Note'])
    expect([...source.options].map((o) => o.textContent)).toEqual(['All sources', 'Obsidian', 'Claude (MCP)', 'Practice Tracker'])
  })

  it('maps filters onto GET /notes params: Practice Tracker is origin=app, never a source_system', () => {
    expect(filtersToParams({})).toEqual({})
    expect(filtersToParams({ q: 'x', kind: 'lecture', source: 'obsidian', origin: 'source', includeDeleted: true })).toEqual({
      q: 'x',
      kind: 'lecture',
      source_system: 'obsidian',
      origin: 'source',
      include_deleted: true,
    })
    expect(filtersToParams({ source: 'app' })).toEqual({ origin: 'app' })
    expect(filtersToParams({ origin: 'app', source: 'llm' })).toEqual({ origin: 'app', source_system: 'llm' })
  })

  it('shows the empty state from ListPhone, with the how-syncing link only when given', () => {
    const onNew = vi.fn()
    const c = list({ items: [], onNew, howSyncingHref: '/help/syncing' })
    const t = text(q(c, '[data-empty]'))
    expect(t).toContain('No notes yet')
    expect(t).toContain('Keep masterclass, lecture and reading notes next to the pieces they mention.')
    expect(t).toContain('Already write in Obsidian?')
    expect(t).toContain('Ask Claude to “sync my Roy Howat note”.')
    click(buttonByText(c, 'Write a note'))
    expect(onNew).toHaveBeenCalledTimes(1)
    expect(text(q(c, '[data-empty] a'))).toBe('How syncing works')
    expect(q(list({ items: [] }), '[data-empty] a')).toBeNull()
  })

  it('tells "no matches" from "no notes" and clears the filters', () => {
    const onFiltersChange = vi.fn()
    const c = list({ items: [], filters: { q: 'zzz' }, onFiltersChange })
    expect(q(c, '[data-empty]')).toBeNull()
    expect(text(q(c, '[data-no-matches]'))).toContain('No notes match these filters')
    click(buttonByText(c, 'Clear filters'))
    expect(onFiltersChange).toHaveBeenCalledWith(EMPTY_FILTERS)
  })

  it('announces loading and errors, and pages with Load more', () => {
    expect(text(q(list({ items: [], loading: true }), '[role=status]'))).toBe('Loading notes…')
    expect(text(q(list({ items: [], error: new Error('boom') }), '[role=alert]'))).toBe('Could not load notes: boom')
    const onLoadMore = vi.fn()
    click(buttonByText(list({ onLoadMore }), 'Load more'))
    expect(onLoadMore).toHaveBeenCalledTimes(1)
  })

  it('asks the host to refresh when a signed thumbnail has expired', () => {
    const onAttachmentExpired = vi.fn()
    const c = list({ onAttachmentExpired })
    act(() => void q(c, 'img').dispatchEvent(new Event('error')))
    expect(onAttachmentExpired).toHaveBeenCalledTimes(1)
  })

  it('lays out for a phone: filter chips, short badges, shorter meta, no thumbnails', () => {
    const c = list({ layout: 'phone' })
    expect(q(c, '[data-notes-list]').dataset.layout).toBe('phone')
    expect(q(c, 'img')).toBeNull()
    const row = text(q(c, 'li[data-note-id="1"]'))
    expect(row).toContain('Obsidian')
    expect(row).not.toContain('Imported ·')
    expect(row).toContain('Masterclass · Ada Keller · 18 Oct')
    expect(row).toContain('+12 · 15 images')
    expect(row).toContain('Synced 2 days ago')
    expect(text(q(c, 'li[data-note-id="3"]'))).toContain('Claude · MCP')
    expect(text(q(c, '[data-sync-line]'))).toBe('Last sync · Obsidian “ExampleVault” · 2 days ago')
    expect(buttonByText(c, 'Kind')).toBeTruthy()
    expect(q(c, 'select')).toBeNull()
  })

  it('opens the phone Kind menu, picks with the keyboard and closes on Escape', () => {
    const onFiltersChange = vi.fn()
    const c = list({ layout: 'phone', onFiltersChange })
    const trigger = qa(c, 'button').find((b) => text(b) === 'Kind')
    click(trigger)
    expect(trigger.getAttribute('aria-expanded')).toBe('true')
    const options = qa(c, '[role=option]')
    expect(options.map(text)).toContain('Masterclass')
    keydown(options[0], 'ArrowDown')
    expect(document.activeElement).toBe(options[1])
    keydown(options[1], 'Escape')
    expect(q(c, '[role=listbox]')).toBeNull()
    expect(document.activeElement).toBe(trigger)
    click(trigger)
    click(qa(c, '[role=option]').find((o) => text(o) === 'Lecture'))
    expect(onFiltersChange).toHaveBeenLastCalledWith({ ...EMPTY_FILTERS, kind: 'lecture' })
  })

  it('renders the schema example list', () => {
    const data = example('NoteList')
    expect(checkShape('NoteList', data).ok).toBe(true)
    const c = mount(h(NotesList, { items: data.items, syncSources: data.sync_sources, now: NOW, layout: 'desktop' }))
    expect(qa(c, 'li[data-note-id]').length).toBe(data.items.length)
  })
})

describe('NoteCard (DayDesk, DayPhone, TodayDesk)', () => {
  const images = [1, 2, 3, 4].map((n) => ({ content_url: `https://notes.example.test/i${n}.webp`, filename: `${n}.webp` }))
  const card = (props = {}) =>
    mount(
      h(NoteCard, {
        summary: { ...howat, last_synced_at: '2026-10-18T11:05:00' },
        excerpt: 'So Op. 10 nº 3 is meant to be an operatic piece.',
        images,
        hrefForNote: (id) => `/notes/${id}`,
        layout: 'desktop',
        timeZone: 'UTC',
        now: NOW,
        ...props,
      }),
    )

  it('draws the Day card: title link, meta, badges, excerpt, images, chips and footer', () => {
    const c = card()
    const root = q(c, '[data-note-card=day]')
    expect(text(q(root, 'h3 a'))).toBe('2026-10-18 Ada Keller')
    expect(q(root, 'h3 a').getAttribute('href')).toBe('/notes/1')
    expect(text(root)).toContain('Masterclass · with Ada Keller · 25 min')
    expect(text(root)).toContain('Obsidian')
    expect(text(q(root, '[data-review-badge]'))).toBe('1 to review')
    expect(q(root, '[data-review-badge]').getAttribute('href')).toBe('/notes/1')
    expect(text(q(root, '[data-excerpt]'))).toBe('So Op. 10 nº 3 is meant to be an operatic piece.')
    expect(qa(root, '[data-images] img').length).toBe(4)
    expect(text(q(root, '[data-more-images]'))).toBe('+11 images')
    expect(text(q(root, '[data-footer]'))).toBe('Synced 11:05 · 3 action items added to backlog Open note')
    expect(text(root)).toContain('+10 more')
    expect(qa(root, '[data-entity-type]').length).toBe(4)
  })

  it('links the chips when the host can route entities', () => {
    const c = card({ hrefForEntity: (type, id) => `/${type}/${id}` })
    expect(q(c, 'a[data-entity-id="35"]').getAttribute('href')).toBe('/repertoire/35')
  })

  it('takes imageCount over the number of images passed', () => {
    const c = card({ images: images.slice(0, 2), imageCount: 6 })
    expect(qa(c, '[data-images] img').length).toBe(2)
    expect(text(q(c, '[data-more-images]'))).toBe('+4 images')
  })

  it('lets the host replace the footer line', () => {
    const c = card({ footer: 'Added by Claude' })
    expect(text(q(c, '[data-footer]'))).toBe('Added by Claude Open note')
  })

  it('asks the host to refresh when a signed image has expired', () => {
    const onAttachmentExpired = vi.fn()
    const c = card({ onAttachmentExpired })
    act(() => void q(c, '[data-images] img').dispatchEvent(new Event('error')))
    expect(onAttachmentExpired).toHaveBeenCalledTimes(1)
  })

  it('makes the badge a button when the host reviews in place', () => {
    const onReview = vi.fn()
    const c = card({ onReview })
    const badge = q(c, 'button[data-review-badge]')
    click(badge)
    expect(onReview).toHaveBeenCalledWith(expect.objectContaining({ id: 1 }))
  })

  it('lays out the phone card: 3 images, short chips, badges row and Open', () => {
    const c = card({ layout: 'phone' })
    const root = q(c, '[data-note-card=day]')
    expect(text(root)).toContain('Masterclass · Ada Keller · 25 min')
    expect(qa(root, '[data-images] img').length).toBe(3)
    expect(text(q(root, '[data-more-images]'))).toBe('+12')
    expect(qa(root, '[data-entity-type]').length).toBe(2)
    expect(text(root)).toContain('+12')
    expect(text([...root.querySelectorAll('a')].at(-1))).toBe('Open')
    expect(q(root, '[data-footer]')).toBeNull()
  })

  it('draws the Today card with the suggestion count', () => {
    const c = card({ variant: 'today', summary: { ...howat, review_pending: 26 } })
    const root = q(c, '[data-note-card=today]')
    expect(root.querySelector('a').getAttribute('href')).toBe('/notes/1')
    expect(text(root)).toContain('Masterclass note')
    expect(text(root)).toContain('2026-10-18 Ada Keller')
    expect(text(root)).toContain('Études, Op.10 · Etudes Op.25 · In the Mists')
    expect(text(root)).toContain('26 suggestions to review')
    expect(text(q(root, '[data-more-images]'))).toBe('+12')
    expect(qa(root, 'img').length).toBe(3)
    expect(root.querySelectorAll('a a').length).toBe(0)
  })

  it('draws the compact Today card on a phone', () => {
    const c = card({ variant: 'today', layout: 'phone', summary: { ...howat, review_pending: 26 } })
    const t = text(q(c, '[data-note-card=today]'))
    expect(t).toContain('Masterclass')
    expect(t).toContain('15 images · Études, Op.10, Etudes Op.25 +12')
    expect(t).toContain('26 suggestions to review')
    expect(q(c, 'img')).toBeNull()
  })

  it('draws a feed card without images and with the activity phrase', () => {
    const c = card({ variant: 'feed' })
    const root = q(c, '[data-note-card=feed]')
    expect(q(root, '[data-images]')).toBeNull()
    expect(text(q(root, '[data-activity]'))).toBe('Synced 2 days ago')
    expect(q(root, '[data-footer]')).toBeNull()
  })

  it('does not require a link or any images', () => {
    const c = mount(h(NoteCard, { summary: empty, layout: 'desktop', now: NOW }))
    expect(q(c, 'h3 a')).toBeNull()
    expect(text(q(c, 'h3'))).toBe('2026-10-18 Ada Keller')
    expect(q(c, '[data-images]')).toBeNull()
  })
})

describe('NoteDetailHeader (NoteDesk, NotePhone)', () => {
  const imported = note({
    title: '2026-10-18 Ada Keller',
    person: 'Ada Keller',
    note_date: '2026-10-18',
    source_workspace: 'ExampleVault',
    source_path: 'One on one meetings/2026-10-18 Ada Keller.md',
    source_url: 'obsidian://open?vault=ExampleVault&file=x',
    last_synced_at: '2026-10-18T14:30:00',
    frontmatter: { duration: '25' },
    review_pending: 1,
  })
  const header = (props = {}) =>
    mount(h(NoteDetailHeader, { note: imported, capabilities: { export: true }, onReview: vi.fn(), onExport: vi.fn(), layout: 'desktop', now: NOW, timeZone: 'UTC', ...props }))

  it('draws the imported note like the desktop artboard', () => {
    const c = header()
    const t = text(q(c, '[data-note-header]'))
    expect(t).toContain('Imported · Obsidian · read-only')
    expect(t).toContain('Masterclass')
    expect(text(q(c, 'h1'))).toBe('2026-10-18 Ada Keller')
    expect(t).toContain('Sun 18 Oct 2026 · 25 min · with Ada Keller · ExampleVault / One on one meetings')
    expect(t).toContain('Synced 2 days ago')
    expect(text(q(c, '[data-sync-info] a'))).toBe('Open in Obsidian')
    expect(q(c, '[data-sync-info] a').getAttribute('href')).toBe(imported.source_url)
    expect(t).toContain('Edit it there — the next sync updates this copy.')
  })

  it('offers Review N pick(s) and Export, each only when it can act', () => {
    const onReview = vi.fn()
    const onExport = vi.fn()
    const c = header({ onReview, onExport })
    click(buttonByText(c, 'Review 1 pick'))
    expect(onReview).toHaveBeenCalledWith(expect.objectContaining({ id: imported.id }))
    click(buttonByText(c, 'Export'))
    expect(onExport).toHaveBeenCalledTimes(1)
    expect(buttonByText(header({ note: { ...imported, review_pending: 3 } }), 'Review 3 picks')).toBeTruthy()
    expect(buttonByText(header({ note: { ...imported, review_pending: 0 } }), 'Review 0 picks')).toBeUndefined()
    expect(q(header({ note: { ...imported, review_pending: 0 } }), '[data-review-entry]')).toBeNull()
    expect(q(header({ capabilities: { export: false } }), '[data-export]')).toBeNull()
    expect(q(header({ capabilities: undefined }), '[data-export]')).toBeNull()
    expect(q(header({ onReview: undefined }), '[data-review-entry]')).toBeNull()
  })

  it('never links a script URL', () => {
    const c = header({ note: { ...imported, source_url: 'javascript:alert(1)' } })
    expect(q(c, '[data-sync-info] a')).toBeNull()
    expect(text(q(c, '[data-sync-info]'))).toContain('Synced 2 days ago')
  })

  it('says Written here / Claude and how recently, with no source link', () => {
    const mine = header({ note: { ...imported, origin: 'app', source_system: null, source_url: null, updated_at: '2026-10-19T14:30:00' } })
    const t = text(q(mine, '[data-note-header]'))
    expect(t).toContain('Written here')
    expect(t).toContain('Edited 1 day ago')
    expect(t).not.toContain('Open in')
    const llm = header({ note: { ...imported, origin: 'app', source_system: 'llm', source_url: null, created_at: '2026-10-19T14:30:00' } })
    expect(text(q(llm, '[data-note-header]'))).toContain('Claude · via MCP')
    expect(text(q(llm, '[data-note-header]'))).toContain('Created 1 day ago')
  })

  it('lays out the phone header: short badge, short meta, a review banner', () => {
    const c = header({ layout: 'phone' })
    const t = text(q(c, '[data-note-header]'))
    expect(t).toContain('Obsidian · read-only')
    expect(t).not.toContain('Imported ·')
    expect(t).toContain('Sun 18 Oct · 25 min · Ada Keller')
    expect(t).toContain('Synced 2 days ago · Open in Obsidian')
    expect(t).not.toContain('Edit it there')
    expect(text(q(c, '[data-review-entry]'))).toBe('1 link needs your pick Review')
    expect(q(c, '[data-note-header]').dataset.layout).toBe('phone')
  })

  describe('source deleted', () => {
    const gone = note({
      ...imported,
      deleted_at: '2026-10-20T08:00:00',
      review_pending: 0,
      last_synced_at: '2026-10-18T11:05:00',
      links: [
        { id: 1, entity_type: 'movement', entity_id: 1003, entity_label: 'Études, Op.10 · Nº 3', status: 'confirmed', action_completed: 0, sort_order: 0 },
        { id: 2, entity_type: 'repertoire', entity_id: 35, entity_label: 'Études, Op.10', status: 'confirmed', action_completed: 0, sort_order: 1 },
        { id: 3, entity_type: 'composer', entity_id: 13, entity_label: 'Chopin', status: 'rejected', action_completed: 0, sort_order: 2 },
      ],
    })
    const deleted = (props = {}) =>
      header({ note: gone, hostName: 'PT', onKeepCopy: vi.fn(), onDeleteFromHost: vi.fn(), layout: 'phone', ...props })

    it('draws the NotePhone tombstone copy', () => {
      const c = deleted()
      const t = text(q(c, '[data-note-header]'))
      expect(t).toContain('Source deleted')
      expect(t).toContain('Obsidian · read-only')
      expect(text(q(c, '[role=status]'))).toBe(
        'Deleted in Obsidian on 20 Oct ' +
          'The file is gone from your vault, so this note is hidden from the feed and Day page. The copy and its links stay here, so Études, Op.10 still shows what Ada said. ' +
          'If the file comes back, the next sync restores it.',
      )
      expect(buttonByText(c, 'Keep copy')).toBeTruthy()
      expect(buttonByText(c, 'Delete from PT…')).toBeTruthy()
      expect(t).toContain('Last synced 18 Oct, 11:05 · 2 links kept, marked “source deleted”')
      expect(q(c, '[data-review-entry]')).toBeNull()
      expect(q(c, '[data-sync-info]')).toBeNull()
    })

    it('keeps the copy', async () => {
      const onKeepCopy = vi.fn().mockResolvedValue(undefined)
      const c = deleted({ onKeepCopy })
      await act(async () => buttonByText(c, 'Keep copy').click())
      expect(onKeepCopy).toHaveBeenCalledWith(gone)
    })

    it('shows a failed keep as an alert and re-enables the buttons', async () => {
      const c = deleted({ onKeepCopy: vi.fn().mockRejectedValue(new Error('x')) })
      await act(async () => buttonByText(c, 'Keep copy').click())
      expect(text(q(c, '[role=alert]'))).toBe('Could not keep the copy. Try again.')
      expect(buttonByText(c, 'Keep copy').disabled).toBe(false)
    })

    it('asks before deleting, focusing the safe choice, and deletes only on confirm', async () => {
      const onDeleteFromHost = vi.fn().mockResolvedValue(undefined)
      const c = deleted({ onDeleteFromHost })
      const trigger = buttonByText(c, 'Delete from PT…')
      trigger.focus()
      click(trigger)
      const dialog = q(c, '[role=alertdialog]')
      expect(text(q(dialog, 'h2'))).toBe('Delete this note from PT?')
      expect(text(dialog)).toContain('This removes the copy and its 2 links from PT.')
      expect(dialog.getAttribute('aria-modal')).toBe('true')
      expect(dialog.contains(document.activeElement)).toBe(true)
      expect(text(document.activeElement)).toBe('Cancel')
      expect(onDeleteFromHost).not.toHaveBeenCalled()
      await act(async () => buttonByText(dialog, 'Delete from PT').click())
      expect(onDeleteFromHost).toHaveBeenCalledWith(gone)
      expect(q(c, '[role=alertdialog]')).toBeNull()
    })

    it('cancels from the button, the scrim and Escape, and gives focus back', () => {
      const onDeleteFromHost = vi.fn()
      const c = deleted({ onDeleteFromHost })
      const trigger = buttonByText(c, 'Delete from PT…')
      trigger.focus()
      click(trigger)
      click(buttonByText(q(c, '[role=alertdialog]'), 'Cancel'))
      expect(q(c, '[role=alertdialog]')).toBeNull()
      expect(document.activeElement).toBe(trigger)
      click(trigger)
      keydown(document.activeElement, 'Escape')
      expect(q(c, '[role=alertdialog]')).toBeNull()
      click(trigger)
      act(() => void q(c, '[data-confirm-dialog]').dispatchEvent(new MouseEvent('mousedown', { bubbles: true })))
      expect(q(c, '[role=alertdialog]')).toBeNull()
      expect(onDeleteFromHost).not.toHaveBeenCalled()
    })

    it('keeps Tab inside the dialog', () => {
      const c = deleted()
      click(buttonByText(c, 'Delete from PT…'))
      const dialog = q(c, '[role=alertdialog]')
      const [cancel, confirm] = qa(dialog, 'button')
      confirm.focus()
      keydown(confirm, 'Tab')
      expect(document.activeElement).toBe(cancel)
    })

    it('stays open with an alert when the delete fails', async () => {
      const c = deleted({ onDeleteFromHost: vi.fn().mockRejectedValue(new Error('x')) })
      click(buttonByText(c, 'Delete from PT…'))
      await act(async () => buttonByText(q(c, '[role=alertdialog]'), 'Delete from PT').click())
      const dialog = q(c, '[role=alertdialog]')
      expect(text(q(dialog, '[role=alert]'))).toBe('Could not delete the note. Try again.')
      expect(buttonByText(dialog, 'Delete from PT').disabled).toBe(false)
    })

    it('hides an action the host did not wire, and defaults the host name', () => {
      const c = deleted({ onKeepCopy: undefined, hostName: undefined })
      expect(buttonByText(c, 'Keep copy')).toBeUndefined()
      expect(buttonByText(c, 'Delete from this app…')).toBeTruthy()
    })
  })

  it('renders the schema example note', () => {
    expect(checkShape('Note', example('Note')).ok).toBe(true)
    const c = mount(h(NoteDetailHeader, { note: example('Note'), now: NOW, layout: 'desktop' }))
    expect(text(q(c, 'h1'))).toBe(example('Note').title)
  })
})

describe('NoteRail (NoteDesk)', () => {
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
  const att = (id, over = {}) => ({
    id,
    blob_id: id,
    filename: `${id}.webp`,
    mime: 'image/webp',
    size_bytes: 100_000,
    sha256: `h${id}`,
    content_url: `https://notes.example.test/a${id}.webp`,
    ref_in_markdown: `![[${id}.webp]]`,
    ...over,
  })
  const howatNote = note({
    links: [
      link(1, 'repertoire', 35, 'Études, Op.10'),
      ...[12, 1, 5, 3].map((n, i) => link(10 + i, 'movement', 1000 + n, `Études, Op.10 · Nº ${n}`)),
      link(20, 'movement', 2001, 'Etudes Op.25 · Nº 1'),
      link(21, 'movement', 2006, 'Etudes Op.25 · Nº 6'),
      link(30, 'movement', 3002, 'In the Mists · II'),
      link(40, 'composer', 13, 'Chopin'),
      link(41, 'composer', 21, 'Beethoven'),
      link(42, 'composer', 7, 'Bach'),
      link(50, 'repertoire', 35, 'Études, Op.10', { anchor: 'op-10', action_item: 'Practice Op.10 Nº 12 slowly — drop the hand', lane: 'practice' }),
      link(51, 'movement', 1012, 'Études, Op.10 · Nº 12', { action_item: 'Reference Op. 55 nº 2 for the clock', lane: 'lesson', action_completed: 1 }),
      link(60, 'composer', 99, 'Rejected composer', { status: 'rejected' }),
      link(61, 'technique', 301, 'Pedaling'),
    ],
    attachments: Array.from({ length: 15 }, (_, i) => att(i + 1, { size_bytes: 92_000 })),
    frontmatter: { arp_id: 'x', 'creation date': '2026-10-18 09:03', tags: ['MeetingNote', 'Masterclass'], duration: 25, owner: null },
  })
  const rail = (props = {}) => mount(h(NoteRail, { note: howatNote, ...props }))

  it('groups linked pieces by work with sorted movement numbers', () => {
    const g = groupLinks(howatNote.links)
    expect(g.works.map((w) => [w.label, partsSummary(w.parts)])).toEqual([
      ['Études, Op.10', 'Nº 1, 3, 5, 12'],
      ['Etudes Op.25', 'Nº 1, 6'],
      ['In the Mists', 'II'],
    ])
    expect(g.composers.map((l) => l.entity_label)).toEqual(['Chopin', 'Beethoven', 'Bach'])
    expect(g.other.map((l) => l.entity_label)).toEqual(['Pedaling'])
    expect(g.actions.length).toBe(2)
  })

  it('draws the sections with their counts', () => {
    const root = q(rail(), '[data-note-rail]')
    const t = text(root)
    expect(root.tagName).toBe('ASIDE')
    expect(root.getAttribute('aria-label')).toBe('Links and attachments')
    expect(t).toContain('Linked pieces · 3')
    expect(t).toContain('Nº 1, 3, 5, 12')
    expect(t).toContain('Composers · 3')
    expect(t).toContain('Other links · 1')
    expect(t).toContain('Action items · 2')
    expect(t).not.toContain('Rejected composer')
  })

  it('shows action items with lane badges and strikes completed ones', () => {
    const items = qa(rail(), '[data-action]')
    expect(text(items[0])).toBe('Practice Op.10 Nº 12 slowly — drop the hand Practice')
    expect(text(items[1])).toBe('Reference Op. 55 nº 2 for the clock Lesson Done')
    const custom = qa(rail({ laneFor: () => null }), '[data-action]')
    expect(text(custom[0])).toBe('Practice Op.10 Nº 12 slowly — drop the hand')
  })

  it('links chips through hrefForEntity, preferring the work link', () => {
    const c = rail({ hrefForEntity: (type, id) => `/${type}/${id}` })
    const chip = qa(c, '[data-rail-section=pieces] a')[0]
    expect(chip.getAttribute('href')).toBe('/repertoire/35')
    expect(q(c, '[data-rail-section=composers] a[data-entity-id="13"]').getAttribute('href')).toBe('/composer/13')
    expect(q(rail(), '[data-rail-section=composers] a')).toBeNull()
  })

  it('shows 10 images then +N, the total size and the expiry note', () => {
    const c = rail()
    const section = q(c, '[data-rail-section=images]')
    expect(text(q(section, 'h2'))).toBe('Images · 15')
    expect(qa(section, 'img').length).toBe(10)
    expect(text(q(section, '[data-more-images]'))).toBe('+5')
    expect(text(section)).toContain('1.32 MB · links expire after 1 h and refresh automatically')
    click(q(section, '[data-more-images]'))
    expect(qa(section, 'img').length).toBe(15)
    expect(q(section, '[data-more-images]')).toBeNull()
  })

  it('counts only images, and asks the host to refresh an expired one', () => {
    const onAttachmentExpired = vi.fn()
    const pdf = att(99, { mime: 'application/pdf', filename: 'x.pdf' })
    const c = rail({ note: { ...howatNote, attachments: [att(1), pdf] }, onAttachmentExpired })
    expect(text(q(c, '[data-rail-section=images] h2'))).toBe('Images · 1')
    act(() => void q(c, '[data-rail-section=images] img').dispatchEvent(new Event('error')))
    expect(onAttachmentExpired).toHaveBeenCalledTimes(1)
  })

  it('lists frontmatter as properties without the sync identity', () => {
    const t = text(q(rail(), '[data-rail-section=properties]'))
    expect(t).toContain('creation date 2026-10-18 09:03')
    expect(t).toContain('tags MeetingNote, Masterclass')
    expect(t).toContain('duration 25')
    expect(t).toContain('owner —')
    expect(t).not.toContain('arp id')
  })

  it('renders nothing for a note with nothing to show', () => {
    const c = rail({ note: note({ links: [], attachments: [], frontmatter: { arp_id: 'x' } }) })
    expect(q(c, '[data-note-rail]')).toBeNull()
  })

  it('formats movement numbers', () => {
    expect(partsSummary(['3', '1', '12'])).toBe('Nº 1, 3, 12')
    expect(partsSummary(['II'])).toBe('II')
    expect(partsSummary(['II', '3'])).toBe('3, II')
    expect(partsSummary([])).toBe('')
  })

  it('renders the schema example note', () => {
    const c = mount(h(NoteRail, { note: example('Note') }))
    expect(q(c, '[data-note-rail]')).not.toBeNull()
  })

  it('shows the lane badge carried by a served example link (K§13.3)', () => {
    const c = mount(h(NoteRail, { note: example('Note') }))
    const item = q(c, '[data-action]')
    expect(item.textContent).toContain('Practise the left hand alone at 60 bpm.')
    expect(item.textContent).toContain('Practice')
  })
})
