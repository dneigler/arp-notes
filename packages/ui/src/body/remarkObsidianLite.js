// remarkObsidianLite: the Obsidian constructs a notes viewer needs, as a remark plugin.
//
//   ![[f]] ![[f|WxH]] ![[f|W]]   -> <img> from attachments[ref_in_markdown].content_url (exact text);
//                                   no attachment -> a labelled placeholder (<arpn-embed-missing>)
//   [[Page]] [[Page|alias]]       -> <arpn-wikilink> (a neutral span: the target is not navigable here)
//   ```dataview fence             -> <arpn-dataview> (collapsed, 'Obsidian query — not rendered here')
//   **Key**:: value               -> <dl class="arpn-fields"> definition rows
//   `=expr` inline                -> muted code (class arpn-inline-query)
//   yaml frontmatter node         -> removed (NoteBody also blanks frontmatter before parsing)
//
// Nothing is dropped: every source line's text stays in the rendered output. Custom element names
// (arpn-*) are mapped to components by NoteBody and render as plain unknown elements without it.
import { element, isOpaque, text } from './tree.js'

const IMAGE_EXT = /\.(?:png|jpe?g|gif|webp|avif|svg|bmp|heic)$/i
const WIKI = /(!?)\[\[([^[\]\n]+?)\]\]/g

function splitAlias(inner) {
  const bar = inner.indexOf('|')
  return bar === -1 ? [inner, null] : [inner.slice(0, bar), inner.slice(bar + 1)]
}

/** '300' -> {width: 300}; '438x282' -> {width: 438, height: 282}; anything else -> {}. */
function embedSize(option) {
  if (!option) return {}
  const wh = /^(\d+)x(\d+)$/.exec(option.trim())
  if (wh) return { width: Number(wh[1]), height: Number(wh[2]) }
  const w = /^(\d+)$/.exec(option.trim())
  return w ? { width: Number(w[1]) } : {}
}

function embedNode(match, target, option, attachments) {
  const attachment = attachments.get(match)
  const name = target.split('#')[0]
  if (attachment && attachment.mime?.startsWith('image/')) {
    return {
      type: 'image',
      url: attachment.content_url,
      alt: attachment.filename,
      data: { hProperties: { className: ['arpn-embed'], 'data-embed': attachment.filename, ...embedSize(option) } },
    }
  }
  if (attachment) {
    return {
      type: 'link',
      url: attachment.content_url,
      children: [text(attachment.filename)],
      data: { hProperties: { className: ['arpn-embed-file'], 'data-embed': attachment.filename } },
    }
  }
  const kind = IMAGE_EXT.test(name) ? 'image' : /\.[A-Za-z0-9]{1,5}$/.test(name) ? 'file' : 'note'
  return element('arpn-embed-missing', { 'data-kind': kind, 'data-name': target, ...embedSize(option) }, [text(target)])
}

function expandText(value, attachments) {
  const out = []
  let last = 0
  for (const m of value.matchAll(WIKI)) {
    if (m.index > last) out.push(text(value.slice(last, m.index)))
    const [target, option] = splitAlias(m[2])
    if (m[1]) out.push(embedNode(m[0], target, option, attachments))
    else out.push(element('arpn-wikilink', { 'data-target': target }, [text(option ?? target)]))
    last = m.index + m[0].length
  }
  if (!out.length) return null
  if (last < value.length) out.push(text(value.slice(last)))
  return out
}

/** Splits inline children into lines at '\n' inside text nodes. */
function toLines(children) {
  const lines = [[]]
  for (const child of children) {
    if (child.type !== 'text' || !child.value.includes('\n')) {
      lines.at(-1).push(child)
      continue
    }
    const parts = child.value.split('\n')
    parts.forEach((part, i) => {
      if (i > 0) lines.push([])
      if (part) lines.at(-1).push(text(part))
    })
  }
  return lines
}

/** A '**Key**:: value' line -> {key, value: inline nodes}, else null. */
function fieldLine(line) {
  const [strong, rest] = line
  if (strong?.type !== 'strong' || strong.children.length !== 1 || strong.children[0].type !== 'text') return null
  if (rest?.type !== 'text' || !rest.value.startsWith('::')) return null
  const value = [text(rest.value.slice(2).replace(/^[ \t]+/, '')), ...line.slice(2)].filter((n) => n.type !== 'text' || n.value)
  return { key: strong.children[0].value, value }
}

function joinLines(lines) {
  const out = []
  lines.forEach((line, i) => {
    if (i > 0) out.push(text('\n'))
    out.push(...line)
  })
  return out
}

function fieldRows(paragraph) {
  const lines = toLines(paragraph.children)
  const parsed = lines.map(fieldLine)
  if (!parsed.some(Boolean)) return null
  const out = []
  let i = 0
  while (i < lines.length) {
    const field = parsed[i] !== null
    let j = i
    while (j < lines.length && (parsed[j] !== null) === field) j++
    if (field) {
      const rows = parsed.slice(i, j).map(({ key, value }) =>
        element('div', { className: ['arpn-field'] }, [
          element('dt', {}, [text(key)]),
          element('dd', {}, value),
        ]),
      )
      out.push(element('dl', { className: ['arpn-fields'] }, rows))
    } else {
      out.push({ type: 'paragraph', children: joinLines(lines.slice(i, j)) })
    }
    i = j
  }
  return out
}

function transformChildren(parent, attachments) {
  const next = []
  for (const child of parent.children) {
    if (child.type === 'yaml') continue
    if (child.type === 'code' && /^dataview(?:js)?$/i.test(child.lang ?? '')) {
      next.push(element('arpn-dataview', { 'data-lang': child.lang, 'data-source': child.value }))
      continue
    }
    if (child.type === 'paragraph') {
      const rows = fieldRows(child)
      if (rows) {
        for (const row of rows) {
          if (row.children) transformChildren(row, attachments)
          next.push(row)
        }
        continue
      }
    }
    if (child.type === 'inlineCode' && child.value.startsWith('=')) {
      child.data = { ...child.data, hProperties: { className: ['arpn-inline-query'] } }
      next.push(child)
      continue
    }
    if (child.type === 'text') {
      const expanded = expandText(child.value, attachments)
      if (expanded) next.push(...expanded)
      else next.push(child)
      continue
    }
    if (child.children && !isOpaque(child)) transformChildren(child, attachments)
    next.push(child)
  }
  parent.children = next
}

/**
 * @param {{attachments?: Array<{ref_in_markdown: string, content_url: string, filename: string, mime?: string}>}} [options]
 */
export function remarkObsidianLite({ attachments = [] } = {}) {
  const byRef = new Map(attachments.map((a) => [a.ref_in_markdown, a]))
  return (tree) => {
    transformChildren(tree, byRef)
  }
}
