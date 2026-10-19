import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'
import { anchorSlug, scanBlockIds, scanHeadings } from '../src/body/anchors.js'

// The table core's tests also run: the UI and core slugs must not drift (K§7).
const TABLE = JSON.parse(readFileSync(new URL('../../core/tests/data/anchor_slugs.json', import.meta.url), 'utf8'))

describe('anchorSlug mirrors core arp_notes.anchors.slug', () => {
  it.each(TABLE.map((row) => [row.heading, row.slug]))('%j -> %j', (heading, slug) => {
    expect(anchorSlug(heading)).toBe(slug)
  })
})

describe('scanHeadings / scanBlockIds mirror the core scans', () => {
  const md = '# Top\ntext\n## Op. 10 No. 3 ##\n```\n# not a heading to a parser, but core counts it\n```\nA line. ^abc-1\nno id here\n^solo'

  it('finds ATX headings with level, 1-based line and slug (fences are not special, as in core)', () => {
    expect(scanHeadings(md)).toEqual([
      { line: 1, level: 1, text: 'Top', anchor: 'top' },
      { line: 3, level: 2, text: 'Op. 10 No. 3', anchor: 'op-10-no-3' },
      { line: 5, level: 1, text: 'not a heading to a parser, but core counts it', anchor: 'not-a-heading-to-a-parser-but-core-counts-it' },
    ])
  })

  it('finds trailing block ids', () => {
    expect(scanBlockIds(md)).toEqual([
      { line: 7, anchor: '^abc-1' },
      { line: 9, anchor: '^solo' },
    ])
  })
})
