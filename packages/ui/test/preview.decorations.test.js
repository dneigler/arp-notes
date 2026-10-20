// @vitest-environment jsdom
// The live-preview decorations as a pure function of an EditorState: which lines are sized, which markers
// are dimmed, what the cursor line reveals, which images are found.
import { EditorSelection, EditorState } from '@codemirror/state'
import { Decoration, WidgetType } from '@codemirror/view'
import { describe, expect, it } from 'vitest'
import { markdownLanguage } from '../src/editor/index.js'
import { activeLineStarts, findImages, previewDecorations } from '../src/preview/decorations.js'

function stateOf(doc, selection) {
  return EditorState.create({ doc, selection, extensions: [markdownLanguage.extension, EditorState.allowMultipleSelections.of(true)] })
}

class Probe extends WidgetType {
  constructor(image) {
    super()
    this.image = image
  }
}

/** [{from, to, kind, class?, image?}] in document order. */
function decorationsOf(state, options = {}) {
  const set = previewDecorations(state, options)
  const found = []
  set.between(0, state.doc.length, (from, to, value) => {
    const spec = value.spec
    found.push({
      from,
      to,
      kind: spec.widget ? 'widget' : value.point ? 'line' : from === to ? 'line' : 'mark',
      class: spec.class,
      image: spec.widget?.image,
    })
  })
  return found
}

const classesAt = (found, pos) => found.filter((d) => d.from === pos && d.class).map((d) => d.class)
const marksOnly = (found) => found.filter((d) => d.class === 'arpn-lp-mark').map((d) => [d.from, d.to])
const imageWidget = (image) => new Probe(image)

describe('headings', () => {
  const doc = '# One\n## Two\n### Three\n#### Four\n\nplain\n\nTitle\n=====\n'
  const found = decorationsOf(stateOf(doc, EditorSelection.cursor(doc.length)))

  it.each([
    ['# One', 'arpn-lp-h1'],
    ['## Two', 'arpn-lp-h2'],
    ['### Three', 'arpn-lp-h3'],
    ['#### Four', 'arpn-lp-h4'],
  ])('sizes the line %j as %s', (text, cls) => {
    expect(classesAt(found, doc.indexOf(text))).toContain(cls)
  })

  it('leaves a plain line alone', () => {
    expect(classesAt(found, doc.indexOf('plain'))).toEqual([])
  })

  it('sizes a Setext heading line but not its underline', () => {
    expect(classesAt(found, doc.indexOf('Title'))).toContain('arpn-lp-h1')
    expect(classesAt(found, doc.indexOf('====='))).not.toContain('arpn-lp-h1')
  })
})

describe('markers', () => {
  it('dims heading, emphasis, code, quote and list markers off the cursor line', () => {
    const doc = '# Head\n\nSome **bold** and *it* and `code`\n\n> quoted\n\n- item\n'
    const found = decorationsOf(stateOf(doc, EditorSelection.cursor(doc.length)))
    const dimmed = marksOnly(found).map(([from, to]) => doc.slice(from, to))
    expect(dimmed).toEqual(expect.arrayContaining(['#', '**', '*', '`', '>', '-']))
    expect(dimmed.filter((m) => m === '**')).toHaveLength(2)
  })

  it('shows the cursor line as written: its markers are not dimmed, and the line is banded', () => {
    const doc = '# Head\n\nSome **bold** text\n\n- item\n'
    const at = doc.indexOf('bold')
    const found = decorationsOf(stateOf(doc, EditorSelection.cursor(at)))
    const dimmed = marksOnly(found)
    const lineStart = doc.indexOf('Some')
    expect(dimmed.some(([from]) => from >= lineStart && from < doc.indexOf('\n', lineStart))).toBe(false)
    expect(classesAt(found, lineStart)).toContain('arpn-lp-active')
    // The other lines still dim.
    expect(dimmed.map(([from, to]) => doc.slice(from, to))).toEqual(expect.arrayContaining(['#', '-']))
  })

  it('reveals every line a selection touches, not a line it only reaches the start of', () => {
    const doc = '# A\n# B\n# C\n'
    const selected = decorationsOf(stateOf(doc, EditorSelection.range(0, doc.indexOf('# C'))))
    expect(classesAt(selected, 0)).toContain('arpn-lp-active')
    expect(classesAt(selected, doc.indexOf('# B'))).toContain('arpn-lp-active')
    expect(classesAt(selected, doc.indexOf('# C'))).not.toContain('arpn-lp-active')
    expect(marksOnly(selected).map(([from]) => from)).toEqual([doc.indexOf('# C')])
  })

  it('keeps the heading size on the cursor line', () => {
    const doc = '# Head\ntext'
    const found = decorationsOf(stateOf(doc, EditorSelection.cursor(3)))
    expect(classesAt(found, 0)).toEqual(expect.arrayContaining(['arpn-lp-h1', 'arpn-lp-active']))
  })

  it('treats every cursor of a multi-cursor selection as a cursor line', () => {
    const doc = '# A\n# B\n# C\n'
    const sel = EditorSelection.create([EditorSelection.cursor(1), EditorSelection.cursor(doc.indexOf('# C') + 1)], 0)
    const found = decorationsOf(stateOf(doc, sel))
    expect([...activeLineStarts(stateOf(doc, sel))]).toEqual([0, doc.indexOf('# C')])
    expect(marksOnly(found).map(([from]) => from)).toEqual([doc.indexOf('# B')])
  })

  it('only decorates the ranges it is given', () => {
    const doc = '# A\n\n# B\n\n# C\n'
    const only = decorationsOf(stateOf(doc, EditorSelection.cursor(doc.length)), { ranges: [{ from: doc.indexOf('# B'), to: doc.indexOf('# B') + 3 }] })
    expect(classesAt(only, 0)).toEqual([])
    expect(classesAt(only, doc.indexOf('# B'))).toContain('arpn-lp-h1')
  })
})

describe('images', () => {
  const doc = 'Before\n![IMG_2040.png](attachment://41)\n![[Howat.png|438x282]]\n![[notes.md]]\n![uploading x…](attachment://pending-abc)\n`![in code](attachment://9)`\n'

  it('finds attachment images and Obsidian image embeds, with the exact Markdown as their text', () => {
    const images = findImages(doc)
    expect(images.map((i) => i.text)).toEqual(['![IMG_2040.png](attachment://41)', '![[Howat.png|438x282]]', '![in code](attachment://9)'])
    expect(images[0]).toMatchObject({ kind: 'attachment', id: '41', target: 'attachment://41', alt: 'IMG_2040.png' })
    expect(images[1]).toMatchObject({ kind: 'embed', target: 'Howat.png', alt: 'Howat.png', width: 438, height: 282 })
  })

  it('reads a width-only embed, ignores an embed of a note, and leaves upload placeholders as source', () => {
    expect(findImages('![[a.png|300]]')[0]).toMatchObject({ width: 300 })
    expect(findImages('![[a.png|300]]')[0].height).toBeUndefined()
    expect(findImages('![[Some note]]')).toEqual([])
    expect(findImages('![x](attachment://pending-1)')).toEqual([])
  })

  it('draws a widget over each image away from the cursor, and none inside code', () => {
    const found = decorationsOf(stateOf(doc, EditorSelection.cursor(0)), { imageWidget })
    const widgets = found.filter((d) => d.kind === 'widget')
    expect(widgets.map((w) => doc.slice(w.from, w.to))).toEqual(['![IMG_2040.png](attachment://41)', '![[Howat.png|438x282]]'])
  })

  it('shows the Markdown while the cursor is inside the image, a selection overlaps it, and not at its edges', () => {
    const from = doc.indexOf('![IMG_2040')
    const to = from + '![IMG_2040.png](attachment://41)'.length
    const widgetsWith = (selection) => decorationsOf(stateOf(doc, selection), { imageWidget }).filter((d) => d.kind === 'widget' && d.from === from)
    expect(widgetsWith(EditorSelection.cursor(from + 5))).toHaveLength(0)
    expect(widgetsWith(EditorSelection.range(from - 2, from + 3))).toHaveLength(0)
    expect(widgetsWith(EditorSelection.cursor(from))).toHaveLength(1)
    expect(widgetsWith(EditorSelection.cursor(to))).toHaveLength(1)
  })

  it('keeps images as source when no widget factory is given', () => {
    expect(decorationsOf(stateOf(doc, EditorSelection.cursor(0))).filter((d) => d.kind === 'widget')).toEqual([])
  })

  it('does not dim the brackets of an image it draws', () => {
    const one = '![alt](attachment://1)\n\ntext'
    const drawn = decorationsOf(stateOf(one, EditorSelection.cursor(one.length)), { imageWidget })
    expect(marksOnly(drawn)).toEqual([])
    const source = decorationsOf(stateOf(one, EditorSelection.cursor(one.length)))
    expect(marksOnly(source).length).toBeGreaterThan(0)
  })
})

it('produces plain decorations: nothing here can change the document', () => {
  const set = previewDecorations(stateOf('# A\n![x](attachment://1)', EditorSelection.cursor(0)), { imageWidget })
  expect(set.size).toBeGreaterThan(0)
  expect(Decoration.none.size).toBe(0)
})
