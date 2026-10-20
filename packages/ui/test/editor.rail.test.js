// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from 'vitest'
import { EditorRail, NoteMetaFields } from '../src/editor/index.js'
import { act, cleanup, h, mount } from './helpers.js'
import { settle } from './editor-helpers.js'

afterEach(cleanup)

const MIB = 1024 * 1024
const CAPS = {
  attachments: true,
  mime_allowlist: ['image/webp', 'image/png', 'application/pdf'],
  limits: { max_attachment_bytes: 25 * MIB },
  export: true,
}
const BODY = [
  'See [@Études, Op.10](ex://repertoire/35) and again [@Études, Op.10](ex://repertoire/35).',
  'Also [@Ghost](ex://repertoire/404) and [@Bach](ex://composer/7).',
  '![shot one.png](attachment://11) ![uploading shot.png…](attachment://pending-abc1)',
  '```',
  '[@In code](ex://repertoire/1) ![x](attachment://99)',
  '```',
].join('\n')
const schemes = [
  {
    prefix: 'ex',
    search: async () => [],
    resolve: vi.fn(async (type, id) => (id === 404 ? null : { title: `${type} ${id}` })),
  },
]

function rail(props = {}) {
  return mount(h(EditorRail, { doc: BODY, schemes, capabilities: CAPS, ...props }))
}

describe('EditorRail', () => {
  it('counts distinct links and finished images, leaving code alone', async () => {
    const el = rail({ attachments: [{ blob_id: 11, filename: 'shot one.png', size_bytes: 1.5 * MIB }] })
    await settle()
    expect(el.querySelector('h2').textContent).toBe('In this note')
    const heads = [...el.querySelectorAll('h3')].map((n) => n.textContent)
    expect(heads).toEqual(['Links · 3', 'Images · 1'])
    expect(el.querySelectorAll('[data-link]')).toHaveLength(3)
    expect(el.querySelector('[data-image=done]').textContent).toBe('shot one.png1.5 MB')
  })

  it('shows a not-found link as such, and resolved titles for the rest', async () => {
    const el = rail()
    await settle()
    const byState = Object.fromEntries([...el.querySelectorAll('[data-link]')].map((n) => [n.dataset.link, n]))
    const ghost = byState['ex://repertoire/404']
    expect(ghost.dataset.state).toBe('missing')
    expect(ghost.textContent).toContain('Ghost')
    expect(ghost.textContent).toContain('not found')
    const found = byState['ex://repertoire/35']
    expect(found.dataset.state).toBe('found')
    expect(found.textContent).toContain('repertoire 35')
    expect(found.textContent).toContain('Piece')
    expect(byState['ex://composer/7'].textContent).toContain('Composer')
  })

  it('links a found chip when the host gives a route, never a missing one', async () => {
    const el = rail({ hrefForEntity: (type, id) => `/${type}/${id}` })
    await settle()
    expect(el.querySelector('[data-link="ex://repertoire/35"] a').getAttribute('href')).toBe('/repertoire/35')
    expect(el.querySelector('[data-link="ex://repertoire/404"] a')).toBeNull()
  })

  it('counts an upload in flight with its percentage', () => {
    const el = rail({ uploads: [{ id: 'pending-abc1', name: 'shot.png', fraction: 0.62, state: 'uploading' }] })
    expect([...el.querySelectorAll('h3')].map((n) => n.textContent)).toEqual(['Links · 3', 'Images · 2'])
    expect(el.querySelector('[data-image=uploading]').textContent).toBe('shot.pnguploading 62%')
  })

  it('does not count a failed upload as an image', () => {
    const el = rail({ uploads: [{ id: 'x', name: 'bad.png', fraction: 0, state: 'error' }] })
    expect([...el.querySelectorAll('h3')].map((n) => n.textContent)[1]).toBe('Images · 1')
  })

  it('says so when there is nothing yet', () => {
    const el = mount(h(EditorRail, { doc: 'plain text', schemes, capabilities: CAPS }))
    expect([...el.querySelectorAll('h3')].map((n) => n.textContent)).toEqual(['Links · 0', 'Images · 0'])
    expect(el.textContent).toContain('No links yet')
    expect(el.textContent).toContain('No images yet')
  })

  it('renders the policy footer from capabilities', () => {
    expect(rail().querySelector('[data-arpn=policy-footer]').textContent).toBe(
      'This app allows Images and PDFs up to 25 MB · export to Markdown on',
    )
    cleanup()
    expect(rail({ capabilities: { ...CAPS, attachments: false, export: false } }).querySelector('[data-arpn=policy-footer]').textContent).toBe(
      'This app doesn’t accept attachments · export to Markdown off',
    )
    cleanup()
    expect(rail({ capabilities: undefined }).querySelector('[data-arpn=policy-footer]')).toBeNull()
  })

  it('takes copy overrides', () => {
    const el = rail({ strings: { railTitle: 'Dans cette note', links: 'Liens' } })
    expect(el.querySelector('h2').textContent).toBe('Dans cette note')
    expect(el.querySelector('h3').textContent).toBe('Liens · 3')
  })
})

describe('NoteMetaFields', () => {
  const kinds = ['masterclass', 'lecture', 'note']

  it('has Title, Kind and Date controls with labels', () => {
    const el = mount(h(NoteMetaFields, { title: 'Roy', kind: 'masterclass', note_date: '2026-10-18', kinds, onChange: () => {} }))
    const label = (text) => document.getElementById([...el.querySelectorAll('label')].find((l) => l.textContent === text).htmlFor)
    expect(label('Title').value).toBe('Roy')
    expect(label('Kind').value).toBe('masterclass')
    expect([...label('Kind').options].map((o) => o.textContent)).toEqual(['Masterclass', 'Lecture', 'Note'])
    expect(label('Date').value).toBe('2026-10-18')
    expect(label('Date').type).toBe('date')
  })

  it('reports just the field that changed (the PATCH body)', () => {
    const onChange = vi.fn()
    const el = mount(h(NoteMetaFields, { title: 'A', kind: 'note', note_date: null, kinds, onChange }))
    const set = (input, value) => {
      const proto = input.tagName === 'SELECT' ? HTMLSelectElement.prototype : HTMLInputElement.prototype
      Object.getOwnPropertyDescriptor(proto, 'value').set.call(input, value)
      act(() => {
        input.dispatchEvent(new Event(input.tagName === 'SELECT' ? 'change' : 'input', { bubbles: true }))
      })
    }
    set(el.querySelector('input[type=text]'), 'AB')
    set(el.querySelector('select'), 'lecture')
    set(el.querySelector('input[type=date]'), '2026-10-19')
    expect(onChange.mock.calls.map((c) => c[0])).toEqual([{ title: 'AB' }, { kind: 'lecture' }, { note_date: '2026-10-19' }])
  })

  it('clearing the date reports null', () => {
    const onChange = vi.fn()
    const el = mount(h(NoteMetaFields, { title: 'A', kind: 'note', note_date: '2026-10-18', kinds, onChange }))
    const input = el.querySelector('input[type=date]')
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(input, '')
    act(() => {
      input.dispatchEvent(new Event('input', { bubbles: true }))
    })
    expect(onChange).toHaveBeenCalledWith({ note_date: null })
  })

  it('keeps showing a kind the host no longer lists', () => {
    const el = mount(h(NoteMetaFields, { title: '', kind: 'legacy', kinds, onChange: () => {} }))
    const select = el.querySelector('select')
    expect(select.value).toBe('legacy')
    expect(select.options).toHaveLength(4)
  })
})
