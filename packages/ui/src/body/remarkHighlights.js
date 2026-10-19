// remarkLinkHighlights: marks each confirmed link's quote in the rendered body.
//
// For every link with a `quote`, the first exact occurrence inside its anchor section is wrapped in
// <mark class="arpn-quote">. A heading anchor's section runs from the heading to the next heading of
// the same or a higher level; '^block-id' means the block that ends with that id; no anchor means the
// whole note. No match, no mark: the rail still lists the link. A link with `backlog_id` gets a
// '→ practice backlog' marker after its quote; `pending` (ambiguous mentions awaiting a pick) gets
// 'needs a pick'. Run it before remarkObsidianLite so quotes copied from the source still match.
import { scanBlockIds, scanHeadings } from './anchors.js'
import { element, isOpaque, text } from './tree.js'

const GROUP_TYPES = new Set(['paragraph', 'heading', 'tableCell'])

/** Phrasing containers in document order, each with the text nodes (and their parents) it holds. */
function textGroups(root) {
  const groups = []
  const visit = (node) => {
    if (GROUP_TYPES.has(node.type)) {
      const texts = []
      const collect = (n) => {
        for (const child of n.children ?? []) {
          if (child.type === 'text') texts.push({ node: child, parent: n })
          else if (!isOpaque(child)) collect(child)
        }
      }
      collect(node)
      groups.push({ container: node, texts })
      return
    }
    for (const child of node.children ?? []) visit(child)
  }
  visit(root)
  return groups
}

function sectionRanges(anchor, headings, lastLine) {
  const matches = headings.filter((h) => h.anchor === anchor)
  return matches.map((h) => {
    const end = headings.find((o) => o.line > h.line && o.level <= h.level)
    return [h.line, end ? end.line - 1 : lastLine]
  })
}

function lineOf(group) {
  return group.container.position?.start.line ?? 0
}

/** Groups that may hold the quote for `anchor`. */
function candidateGroups(groups, anchor, headings, blockIds, lastLine) {
  if (!anchor) return groups
  if (anchor.startsWith('^')) {
    const id = blockIds.find((b) => b.anchor === anchor)
    if (!id) return []
    return groups.filter((g) => {
      const pos = g.container.position
      return pos && pos.start.line <= id.line && id.line <= pos.end.line
    })
  }
  const ranges = sectionRanges(anchor, headings, lastLine)
  return groups.filter((g) => ranges.some(([from, to]) => lineOf(g) > from && lineOf(g) <= to))
}

/** Wraps [start, end) of the group's concatenated text; returns the last mark node created. */
function wrap(group, start, end, markProps) {
  let offset = 0
  let lastMark = null
  let lastParent = null
  for (const { node, parent } of group.texts) {
    const from = offset
    const to = offset + node.value.length
    offset = to
    if (to <= start || from >= end) continue
    const cut0 = Math.max(start, from) - from
    const cut1 = Math.min(end, to) - from
    const pieces = []
    if (cut0 > 0) pieces.push(text(node.value.slice(0, cut0)))
    lastMark = element('mark', markProps, [text(node.value.slice(cut0, cut1))])
    pieces.push(lastMark)
    if (cut1 < node.value.length) pieces.push(text(node.value.slice(cut1)))
    parent.children.splice(parent.children.indexOf(node), 1, ...pieces)
    lastParent = parent
  }
  return { mark: lastMark, parent: lastParent }
}

/**
 * @param {{links?: Array<Object>, pending?: Array<{quote?: string, mention?: string, anchor?: string|null}>}} [options]
 */
export function remarkLinkHighlights({ links = [], pending = [] } = {}) {
  const targets = [
    ...links
      .filter((l) => l.status === undefined || l.status === 'confirmed')
      .filter((l) => l.quote)
      .map((l) => ({ quote: l.quote, anchor: l.anchor ?? null, id: String(l.id ?? ''), backlog: Boolean(l.backlog_id) })),
    ...pending
      .filter((p) => p.quote || p.mention)
      .map((p) => ({ quote: p.quote ?? p.mention, anchor: p.anchor ?? null, id: '', pending: true })),
  ]
  return (tree, file) => {
    if (!targets.length) return
    const source = String(file?.value ?? '')
    const headings = scanHeadings(source)
    const blockIds = scanBlockIds(source)
    const lastLine = source.split('\n').length
    for (const target of targets) {
      const groups = candidateGroups(textGroups(tree), target.anchor, headings, blockIds, lastLine)
      for (const group of groups) {
        const joined = group.texts.map((t) => t.node.value).join('')
        const at = joined.indexOf(target.quote)
        if (at === -1) continue
        const props = { className: [target.pending ? 'arpn-pending' : 'arpn-quote'], 'data-link-id': target.id }
        const { mark, parent } = wrap(group, at, at + target.quote.length, props)
        const label = target.pending ? 'needs a pick' : target.backlog ? '→ practice backlog' : null
        if (label && mark) {
          const marker = element('arpn-marker', { 'data-kind': target.pending ? 'pending' : 'backlog' }, [text(label)])
          parent.children.splice(parent.children.indexOf(mark) + 1, 0, marker)
        }
        break
      }
    }
  }
}
