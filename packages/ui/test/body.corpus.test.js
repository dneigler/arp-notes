// @vitest-environment jsdom
import { afterEach, describe, expect, it } from 'vitest'
import { NoteBody, blankFrontmatter } from '../src/body/index.js'
import { cleanup, fixtureText, h, mount } from './helpers.js'

afterEach(cleanup)

const corpus = fixtureText('obsidian-synthetic.md')

// notes-sync-editor-spike.md §4.1: the 33-construct synthetic corpus.
describe('the synthetic Obsidian corpus (spike §4.1)', () => {
  const attachments = [{ ref_in_markdown: '![[image.png]]', content_url: 'https://x.test/i.png', filename: 'image.png', mime: 'image/png', id: 1, blob_id: 1, size_bytes: 1, sha256: 'a'.repeat(64) }]
  const hrefForEntity = (type, id) => `/${type}/${id}`

  it('renders without throwing, with and without attachments, chips and links', () => {
    expect(() => mount(h(NoteBody, { note: { body_md: corpus }, hrefForEntity }))).not.toThrow()
    expect(() => mount(h(NoteBody, { note: { body_md: corpus, attachments }, hrefForEntity: () => null, schemes: [] }))).not.toThrow()
  })

  it('keeps every source line\'s text', () => {
    const el = mount(h(NoteBody, { note: { body_md: corpus, attachments }, hrefForEntity }))
    const visible = new Set()
    // Tokenise per text node: adjacent elements (a <dt> and its <dd>) have no whitespace between them in textContent.
    const take = (text) => text.match(/[\p{L}\p{N}]+/gu)?.forEach((t) => visible.add(t))
    const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT)
    for (let n = walker.nextNode(); n; n = walker.nextNode()) take(n.nodeValue)
    for (const node of el.querySelectorAll('[alt],[aria-label],[title],[data-embed]')) {
      for (const attr of ['alt', 'aria-label', 'title', 'data-embed']) take(node.getAttribute(attr) ?? '')
    }

    const lines = blankFrontmatter(corpus).split('\n')
    const missing = []
    for (const line of lines) {
      if (/^\s*(?:```|~~~)/.test(line) || /^[\s|:-]*$/.test(line) || /^\s*(?:\*{3,}|(?:- ){2,}-)\s*$/.test(line)) continue
      const expected = line
        .replace(/!?\[\[([^\]|]*)\|([^\]]*)\]\]/g, (m, target, alias) => (/^\d+(x\d+)?$/.test(alias) ? target : alias))
        .replace(/\]\([^)]*\)/g, ']')
      for (const token of expected.match(/[\p{L}\p{N}]+/gu) ?? []) {
        if (!visible.has(token)) missing.push(`${JSON.stringify(token)} from ${JSON.stringify(line)}`)
      }
    }
    expect(missing).toEqual([])
  })

  it('shows the constructs it knows and not the frontmatter', () => {
    const el = mount(h(NoteBody, { note: { body_md: corpus, attachments }, hrefForEntity }))
    expect(el.textContent).not.toContain('arp_id')
    expect(el.textContent).not.toContain('cssclasses')
    expect(el.querySelector('img').getAttribute('src')).toBe('https://x.test/i.png')
    expect(el.querySelectorAll('[data-embed-missing]').length).toBe(4) // sized image, width-only image, note embed, PDF page
    expect(el.querySelectorAll('[data-dataview]').length).toBe(1)
    expect(el.querySelector('code.arpn-inline-query').textContent).toContain('dateformat')
    expect(el.querySelectorAll('dl.arpn-fields > div').length).toBe(2)
    expect(el.querySelector('table')).not.toBeNull()
    expect(el.querySelectorAll('input[type="checkbox"]').length).toBe(3)
    for (const box of el.querySelectorAll('input[type="checkbox"]')) expect(box.getAttribute('aria-label')).toMatch(/^(Done|Not done)$/)
  })
})
