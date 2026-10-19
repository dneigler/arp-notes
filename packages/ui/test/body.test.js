// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from 'vitest'
import { NoteBody } from '../src/body/index.js'
import { act, cleanup, example, h, mount } from './helpers.js'

afterEach(cleanup)

const hrefForEntity = (type, id) => (type === 'repertoire' || type === 'mention' || type === 'composer' ? `/${type}/${id}` : null)

function attachment(ref, extra = {}) {
  return {
    id: 1,
    blob_id: 1,
    filename: 'image.png',
    ref_in_markdown: ref,
    mime: 'image/png',
    size_bytes: 10,
    sha256: 'a'.repeat(64),
    content_url: 'https://notes.example.test/api/v1/attachments/1/content?exp=1&sig=ab',
    ...extra,
  }
}

function link(over) {
  return {
    id: 1,
    entity_type: 'repertoire',
    entity_id: 35,
    entity_label: 'Études, Op. 10',
    action_completed: 0,
    status: 'confirmed',
    sort_order: 0,
    anchor: null,
    quote: null,
    ...over,
  }
}

function render(body_md, props = {}) {
  const note = { body_md, attachments: [], links: [], ...props.note }
  return mount(h(NoteBody, { hrefForEntity, ...props, note }))
}

const marks = (el) => [...el.querySelectorAll('mark')].map((m) => m.textContent)

describe('embeds', () => {
  it('![[f]] becomes an <img> whose src is the attachment content_url, matched by exact text', () => {
    const note = example('Note')
    const el = mount(h(NoteBody, { note, hrefForEntity }))
    const img = el.querySelector('img')
    expect(img.getAttribute('src')).toBe(note.attachments[0].content_url)
    expect(img.getAttribute('alt')).toBe(note.attachments[0].filename)
  })

  it('![[f|WxH]] and ![[f|W]] set the size', () => {
    const a = attachment('![[a.png|438x282]]', { filename: 'a.png' })
    const b = attachment('![[b.webp|300]]', { filename: 'b.webp', mime: 'image/webp', id: 2 })
    const el = render('![[a.png|438x282]]\n\n![[b.webp|300]]', { note: { attachments: [a, b] } })
    const [ia, ib] = el.querySelectorAll('img')
    expect([ia.getAttribute('width'), ia.getAttribute('height')]).toEqual(['438', '282'])
    expect([ib.getAttribute('width'), ib.getAttribute('height')]).toEqual(['300', null])
  })

  it('the match is the exact embed text: a differently-written embed does not borrow another attachment', () => {
    const el = render('![[image.png|300]]', { note: { attachments: [attachment('![[image.png]]')] } })
    expect(el.querySelector('img')).toBeNull()
    expect(el.querySelector('[data-embed-missing="image"]')).not.toBeNull()
  })

  it('a missing image is a labelled placeholder, not a dropped line', () => {
    const el = render('Before ![[gone.webp]] after')
    const ph = el.querySelector('[data-embed-missing="image"]')
    expect(ph.getAttribute('aria-label')).toBe('Image not synced: gone.webp')
    expect(ph.textContent).toContain('gone.webp')
    expect(el.textContent).toContain('Before')
    expect(el.textContent).toContain('after')
  })

  it('a note embed and a PDF page reference get their own labels', () => {
    const el = render('![[Other Note#Heading]] ![[score.pdf#page=3]]')
    expect(el.querySelector('[data-embed-missing="note"]').getAttribute('aria-label')).toBe('Embedded note: Other Note#Heading')
    expect(el.querySelector('[data-embed-missing="file"]').getAttribute('aria-label')).toBe('Attachment not synced: score.pdf#page=3')
  })

  it('a synced non-image attachment becomes a link to its signed URL', () => {
    const pdf = attachment('![[score.pdf]]', { filename: 'score.pdf', mime: 'application/pdf' })
    const el = render('![[score.pdf]]', { note: { attachments: [pdf] } })
    const a = el.querySelector('a.arpn-embed-file, a[data-embed="score.pdf"]')
    expect(a.getAttribute('href')).toBe(pdf.content_url)
    expect(a.textContent).toBe('score.pdf')
  })

  it('an image load error calls onAttachmentExpired once per burst', () => {
    const onAttachmentExpired = vi.fn()
    const a = attachment('![[a.png]]', { filename: 'a.png' })
    const b = attachment('![[b.png]]', { filename: 'b.png', id: 2 })
    const el = render('![[a.png]] ![[b.png]]', { onAttachmentExpired, note: { attachments: [a, b] } })
    const [ia, ib] = el.querySelectorAll('img')
    act(() => ia.dispatchEvent(new Event('error')))
    act(() => ib.dispatchEvent(new Event('error')))
    expect(onAttachmentExpired).toHaveBeenCalledTimes(1)
    expect(onAttachmentExpired).toHaveBeenCalledWith({ src: a.content_url, filename: 'a.png' })
  })

  it('an image error without a handler is harmless', () => {
    const a = attachment('![[a.png]]', { filename: 'a.png' })
    const el = render('![[a.png]]', { note: { attachments: [a] } })
    expect(() => act(() => el.querySelector('img').dispatchEvent(new Event('error')))).not.toThrow()
  })
})

describe('Obsidian constructs', () => {
  it('[[Page]] and [[Page|alias]] are neutral spans, never links', () => {
    const el = render('See [[Roy Howat]] and [[Op.10 nº 3|the E major étude]].')
    expect(el.querySelector('a')).toBeNull()
    const spans = [...el.querySelectorAll('[data-wikilink]')]
    expect(spans.map((s) => [s.getAttribute('data-wikilink'), s.textContent])).toEqual([
      ['Roy Howat', 'Roy Howat'],
      ['Op.10 nº 3', 'the E major étude'],
    ])
  })

  it('a ```dataview fence is collapsed with a Show source toggle that keeps the source in the DOM', () => {
    const el = render('```dataview\nTABLE x FROM "y"\n```')
    const box = el.querySelector('[data-dataview]')
    expect(box.textContent).toContain('Obsidian query — not rendered here')
    const button = box.querySelector('button')
    const pre = box.querySelector('pre')
    expect(button.textContent).toBe('Show source')
    expect(button.getAttribute('aria-expanded')).toBe('false')
    expect(pre.hidden).toBe(true)
    expect(pre.textContent).toContain('TABLE x FROM "y"')
    act(() => button.click())
    expect(button.textContent).toBe('Hide source')
    expect(button.getAttribute('aria-expanded')).toBe('true')
    expect(pre.hidden).toBe(false)
    expect(button.getAttribute('aria-controls')).toBe(pre.id)
  })

  it('other fences stay code blocks', () => {
    const el = render('```python\nprint(1)\n```')
    expect(el.querySelector('[data-dataview]')).toBeNull()
    expect(el.querySelector('pre code').textContent).toContain('print(1)')
  })

  it('**Key**:: value lines become definition rows', () => {
    const el = render('**Attendees**:: [[Roy Howat]]\n**Links**:: [[A]], [[B]]\nplain line after')
    const rows = [...el.querySelectorAll('dl > div')]
    expect(rows.map((r) => r.querySelector('dt').textContent)).toEqual(['Attendees', 'Links'])
    expect(rows[0].querySelector('dd [data-wikilink]').textContent).toBe('Roy Howat')
    expect(rows[1].querySelector('dd').textContent).toBe('A, B')
    expect(el.querySelector('p').textContent).toBe('plain line after')
  })

  it('a paragraph with no ::-fields is left alone', () => {
    const el = render('**Bold** text:: not a field here')
    expect(el.querySelector('dl')).toBeNull()
    expect(el.querySelector('p strong').textContent).toBe('Bold')
  })

  it('inline `=expr` is muted code, plain code is not', () => {
    const el = render('A `=dateformat(this.file.mtime)` and `plain`.')
    const [q, c] = el.querySelectorAll('code')
    expect(q.className).toContain('arpn-inline-query')
    expect(c.className).not.toContain('arpn-inline-query')
  })

  it('frontmatter is stripped for display and body_md is never mutated', () => {
    const note = Object.freeze({
      body_md: '---\narp_id: 5b2f6c1e\ntags: [a]\n---\n# Title\n\nBody.',
      attachments: Object.freeze([]),
      links: Object.freeze([]),
    })
    const before = note.body_md
    const el = mount(h(NoteBody, { note, hrefForEntity }))
    expect(el.textContent).not.toContain('arp_id')
    expect(el.querySelector('h1').textContent).toBe('Title')
    expect(note.body_md).toBe(before)
  })

  it('a note with no body renders an empty container', () => {
    expect(() => mount(h(NoteBody, { note: {}, hrefForEntity }))).not.toThrow()
  })

  it('headings carry their anchor slug for hosts that scroll to it', () => {
    const el = render('# Op. 10 No. 3\n\ntext\n\n## ^weird ##')
    expect(el.querySelector('h1').getAttribute('data-anchor')).toBe('op-10-no-3')
  })
})

describe('host chips', () => {
  const body = 'See [@Études, Op.10](pt://repertoire/35) and [@Old](mention://repertoire/etudes) and [@Nope](pt://person/9) and [web](https://example.com).'
  const schemes = [{ prefix: 'pt', entity_types: ['repertoire', 'composer'] }]

  it('resolves through schemes + hrefForEntity; numeric ids arrive as numbers', () => {
    const hrefs = []
    const el = render(body, { schemes, hrefForEntity: (t, id) => (hrefs.push([t, id]), hrefForEntity(t, id)) })
    const chips = [...el.querySelectorAll('[data-chip="resolved"]')]
    expect(chips.map((c) => [c.textContent, c.getAttribute('href')])).toEqual([
      ['@Études, Op.10', '/repertoire/35'],
      ['@Old', '/repertoire/etudes'],
    ])
    expect(hrefs).toContainEqual(['repertoire', 35])
  })

  it('an unresolved chip keeps its text and reads · not found', () => {
    const el = render(body, { schemes })
    const missing = el.querySelector('[data-chip="missing"]')
    expect(missing.textContent).toBe('@Nope · not found')
    expect(missing.closest('a')).toBeNull()
  })

  it('a scheme the host did not advertise is not found even when hrefForEntity would answer', () => {
    const el = render('[@X](other://repertoire/1)', { schemes })
    expect(el.querySelector('[data-chip="missing"]').textContent).toBe('@X · not found')
  })

  it('without a schemes list, hrefForEntity alone decides', () => {
    const el = render('[@X](other://repertoire/1)')
    expect(el.querySelector('[data-chip="resolved"]').getAttribute('href')).toBe('/repertoire/1')
  })

  it('ordinary web links stay links', () => {
    const el = render(body, { schemes })
    const a = el.querySelector('a[href="https://example.com"]')
    expect(a.textContent).toBe('web')
    expect(a.getAttribute('rel')).toContain('noopener')
  })
})

describe('link highlighting', () => {
  const body = [
    '# Intro',
    'Keep the melody singing and the left hand quiet.',
    '',
    '## Etude 3',
    'Keep the melody singing and the left hand quiet.',
    'Second line with **bold phrase here** inside.',
    '',
    '# Other',
    'Keep the melody singing and the left hand quiet.',
    'A tagged line. ^blk1',
  ].join('\n')

  it('marks the first exact occurrence inside the anchor section only', () => {
    const el = render(body, { links: [link({ anchor: 'etude-3', quote: 'Keep the melody singing and the left hand quiet.' })] })
    expect(marks(el)).toEqual(['Keep the melody singing and the left hand quiet.'])
    const mark = el.querySelector('mark')
    expect(mark.closest('p').previousElementSibling.tagName).toBe('H2')
  })

  it('a section includes its subsections and stops at the next heading of the same or higher level', () => {
    const el = render(body, { links: [link({ anchor: 'intro', quote: 'Second line' })] })
    expect(marks(el)).toEqual(['Second line'])
    const outside = render(body, { links: [link({ anchor: 'etude-3', quote: 'A tagged line.' })] })
    expect(marks(outside)).toEqual([])
  })

  it('a null anchor searches the whole note and marks only the first occurrence', () => {
    const el = render(body, { links: [link({ quote: 'Keep the melody singing and the left hand quiet.' })] })
    expect(marks(el)).toHaveLength(1)
    expect(el.querySelector('mark').closest('p').previousElementSibling.textContent).toBe('Intro')
  })

  it('no match means no mark and nothing breaks', () => {
    const el = render(body, { links: [link({ anchor: 'intro', quote: 'not in the body at all' }), link({ id: 2, anchor: 'missing-heading', quote: 'Second line' })] })
    expect(marks(el)).toEqual([])
    expect(el.textContent).toContain('Second line')
  })

  it('a quote can span inline formatting', () => {
    const el = render(body, { links: [link({ anchor: 'etude-3', quote: 'with bold phrase here inside' }), link({ id: 2, anchor: 'etude-3', quote: 'Second line with ' })] })
    expect(marks(el).join('')).toContain('Second line with ')
    expect(el.textContent).toContain('Second line with bold phrase here inside.')
  })

  it("'^block-id' anchors target the block that ends with that id", () => {
    const el = render(body, { links: [link({ anchor: '^blk1', quote: 'tagged' }), link({ id: 2, anchor: '^nope', quote: 'singing' })] })
    expect(marks(el)).toEqual(['tagged'])
  })

  it('only confirmed links with a quote are highlighted', () => {
    const el = render(body, {
      links: [
        link({ status: 'rejected', quote: 'melody' }),
        link({ id: 2, status: 'orphaned', quote: 'singing' }),
        link({ id: 3, quote: null }),
        link({ id: 4, quote: 'quiet' }),
      ],
    })
    expect(marks(el)).toEqual(['quiet'])
  })

  it("adds '→ practice backlog' after the quote when the link has a backlog_id", () => {
    const el = render(body, { links: [link({ anchor: 'etude-3', quote: 'Second line', backlog_id: 12 })] })
    const marker = el.querySelector('[data-marker="backlog"]')
    expect(marker.textContent).toBe('→ practice backlog')
    expect(el.querySelector('mark').nextElementSibling).toBe(marker)
  })

  it("marks pending ambiguous mentions 'needs a pick' only when pending is given", () => {
    const withPending = render(body, { pending: [{ quote: 'tagged line', anchor: 'other' }] })
    expect(withPending.querySelector('mark.arpn-pending').textContent).toBe('tagged line')
    expect(withPending.querySelector('[data-marker="pending"]').textContent).toBe('needs a pick')
    const without = render(body)
    expect(without.querySelector('[data-marker="pending"]')).toBeNull()
  })

  it('uses note.links when links is not passed, and links wins when it is', () => {
    const note = { links: [link({ quote: 'melody' })] }
    expect(marks(render(body, { note }))).toEqual(['melody'])
    expect(marks(render(body, { note, links: [] }))).toEqual([])
  })

  it('a quote written as source text still matches before wikilink expansion', () => {
    const el = render('Study [[Roy Howat]] closely.', { links: [link({ quote: '[[Roy Howat]]' })] })
    expect(el.querySelector('mark [data-wikilink]').textContent).toBe('Roy Howat')
  })

  it('the Howat-style example note highlights its confirmed link', () => {
    const note = example('Note')
    const el = mount(h(NoteBody, { note, hrefForEntity }))
    expect(marks(el)).toEqual([note.links[0].quote])
  })
})

describe('urls', () => {
  it('embed images may use data: and relative URLs, but javascript: is refused', () => {
    const data = attachment('![[a.png]]', { filename: 'a.png', content_url: 'data:image/png;base64,AAAA' })
    const rel = attachment('![[b.png]]', { filename: 'b.png', id: 2, content_url: '/api/v1/attachments/2/content?exp=1&sig=ab' })
    const bad = attachment('![[c.png]]', { filename: 'c.png', id: 3, content_url: 'javascript:alert(1)' })
    const el = render('![[a.png]] ![[b.png]] ![[c.png]]', { note: { attachments: [data, rel, bad] } })
    const srcs = [...el.querySelectorAll('img')].map((i) => i.getAttribute('src'))
    expect(srcs).toContain('data:image/png;base64,AAAA')
    expect(srcs).toContain('/api/v1/attachments/2/content?exp=1&sig=ab')
    expect(srcs.some((s) => /javascript:/i.test(s ?? ''))).toBe(false)
  })

  it('ordinary Markdown links still lose unsafe protocols', () => {
    const el = render('[x](javascript:alert(1)) and ![y](data:image/png;base64,AAAA)')
    expect(el.querySelector('a').getAttribute('href') ?? '').toBe('')
  })
})
