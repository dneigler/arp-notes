// The live-preview decorations as a pure function of an EditorState (ADR D4, "what it costs"): heading lines
// sized by level, Markdown markers dimmed off the cursor line, the cursor line banded, and inline image
// widgets. Decorations only: the document is never touched, so preview on and off give the same string.
import { ensureSyntaxTree, syntaxTree } from '@codemirror/language'
import { Decoration } from '@codemirror/view'
import { PENDING_PREFIX, inCode } from '../editor/scan.js'

const HEADING = /^(?:ATX|Setext)Heading([1-6])$/

// #, * _ ~~ ` > and list bullets, task boxes, and the brackets of links.
const MARKER_NODES = new Set([
  'HeaderMark',
  'EmphasisMark',
  'StrikethroughMark',
  'CodeMark',
  'CodeInfo',
  'QuoteMark',
  'ListMark',
  'TaskMarker',
  'LinkMark',
])

const MARKER = Decoration.mark({ class: 'arpn-lp-mark' })
const ACTIVE = Decoration.line({ class: 'arpn-lp-active' })
const HEADING_LINES = [1, 2, 3, 4, 5, 6].map((level) => Decoration.line({ class: `arpn-lp-h${level}` }))

// ![alt](attachment://id): an image the editor's own paste/drop path wrote.
const ATTACHMENT_IMAGE = /!\[([^\]\n]*)\]\(attachment:\/\/([^)\s]+)\)/g
// ![[file.png]] ![[file.png|300]] ![[file.png|300x200]]: Obsidian embeds. Only image files are drawn.
const EMBED = /!\[\[([^[\]\n]+?)\]\]/g
const IMAGE_EXT = /\.(?:png|jpe?g|gif|webp|avif|svg|bmp|heic)$/i

/** '300' -> {width: 300}; '438x282' -> {width: 438, height: 282}; anything else -> {}. Same reading as NoteBody. */
function embedSize(option) {
  if (!option) return {}
  const wh = /^(\d+)x(\d+)$/.exec(option.trim())
  if (wh) return { width: Number(wh[1]), height: Number(wh[2]) }
  const w = /^(\d+)$/.exec(option.trim())
  return w ? { width: Number(w[1]) } : {}
}

/**
 * Inline images in `text` (a slice of the document starting at `offset`): `{from, to, kind, text, target, alt,
 * id?, width?, height?}`. `text` is the exact Markdown of the construct, the `ref` a host resolves.
 * Upload placeholders (`attachment://pending-…`) are left as source: the bytes have not landed yet.
 * @param {string} text
 * @param {number} offset
 * @param {(index: number) => boolean} [isCode]  index into `text`
 */
export function findImages(text, offset = 0, isCode) {
  if (!text.includes('![')) return []
  const found = []
  for (const m of text.matchAll(ATTACHMENT_IMAGE)) {
    if (m[2].startsWith(PENDING_PREFIX) || isCode?.(m.index)) continue
    found.push({
      from: offset + m.index,
      to: offset + m.index + m[0].length,
      kind: 'attachment',
      text: m[0],
      target: `attachment://${m[2]}`,
      id: m[2],
      alt: m[1],
    })
  }
  for (const m of text.matchAll(EMBED)) {
    const bar = m[1].indexOf('|')
    const target = (bar === -1 ? m[1] : m[1].slice(0, bar)).trim()
    const name = target.split('#')[0]
    if (!IMAGE_EXT.test(name) || isCode?.(m.index)) continue
    found.push({
      from: offset + m.index,
      to: offset + m.index + m[0].length,
      kind: 'embed',
      text: m[0],
      target,
      alt: name,
      ...embedSize(bar === -1 ? null : m[1].slice(bar + 1)),
    })
  }
  return found.sort((a, b) => a.from - b.from)
}

/** Start positions of the lines a selection touches: the cursor line, or every line of a selected block. */
export function activeLineStarts(state) {
  const starts = new Set()
  for (const range of state.selection.ranges) {
    const first = state.doc.lineAt(range.from)
    let last = state.doc.lineAt(range.to)
    // A selection that ends at the very start of a line has not reached that line.
    if (!range.empty && range.to === last.from && last.number > first.number) last = state.doc.line(last.number - 1)
    for (let n = first.number; n <= last.number; n += 1) starts.add(state.doc.line(n).from)
  }
  return starts
}

/** A selection range is inside the span when the cursor is strictly within it or a selection overlaps it. */
function touches(range, from, to) {
  return range.empty ? range.head > from && range.head < to : range.from < to && range.to > from
}

/**
 * @param {import('@codemirror/state').EditorState} state
 * @param {object} [options]
 * @param {Array<{from: number, to: number}>} [options.ranges]  What to decorate (the visible ranges); default all.
 * @param {(image: object) => import('@codemirror/view').WidgetType|null} [options.imageWidget]
 *   Builds the widget for an image; without it images stay source.
 * @returns {import('@codemirror/view').DecorationSet}
 */
export function previewDecorations(state, { ranges, imageWidget } = {}) {
  const doc = state.doc
  const spans = ranges?.length ? ranges : [{ from: 0, to: doc.length }]
  const end = Math.max(...spans.map((r) => r.to))
  const tree = ensureSyntaxTree(state, end, 25) ?? syntaxTree(state)
  const active = activeLineStarts(state)
  const found = []
  const decoratedLines = new Set()

  const line = (pos, deco) => {
    const key = `${deco.spec.class}@${pos}`
    if (decoratedLines.has(key)) return
    decoratedLines.add(key)
    found.push(deco.range(pos))
  }

  for (const span of spans) {
    const start = doc.lineAt(span.from).from
    const stop = doc.lineAt(span.to).to

    // Images first: a marker inside a drawn image is part of the widget.
    const drawn = []
    if (imageWidget) {
      const text = doc.sliceString(start, stop)
      for (const image of findImages(text, start, (i) => inCode(tree, start + i))) {
        if (state.selection.ranges.some((r) => touches(r, image.from, image.to))) continue
        const widget = imageWidget(image)
        if (!widget) continue
        drawn.push(image)
        found.push(Decoration.replace({ widget }).range(image.from, image.to))
      }
    }
    const insideImage = (from, to) => drawn.some((image) => from >= image.from && to <= image.to)

    tree.iterate({
      from: start,
      to: stop,
      enter(node) {
        const heading = HEADING.exec(node.name)
        if (heading) {
          const first = doc.lineAt(node.from).number
          let last = doc.lineAt(node.to).number
          // A Setext heading's underline (=== or ---) is a marker line, not heading text.
          if (node.name.startsWith('Setext') && last > first) last -= 1
          for (let n = first; n <= last; n += 1) line(doc.line(n).from, HEADING_LINES[Number(heading[1]) - 1])
          return
        }
        if (!MARKER_NODES.has(node.name) || node.to <= node.from) return
        const lineStart = doc.lineAt(node.from).from
        if (active.has(lineStart) || insideImage(node.from, node.to)) return
        found.push(MARKER.range(node.from, node.to))
      },
    })
  }

  for (const lineStart of active) {
    if (spans.some((span) => lineStart >= doc.lineAt(span.from).from && lineStart <= span.to)) line(lineStart, ACTIVE)
  }

  return Decoration.set(found, true)
}
