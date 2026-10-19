// Heading anchors, mirrored byte-for-byte from core's arp_notes/anchors.py (K§7). The shared table
// packages/core/tests/data/anchor_slugs.json is run against both (test/anchors.test.js).

const KEPT = /[\p{L}\p{M}\p{N}\p{Pc}-]/u

/**
 * The anchor for a heading's text (without its '#' markers), or a '^block-id' unchanged.
 * Trim, lower-case, keep letters, marks, numbers, '_' , '-' and spaces, then each space -> '-'.
 */
export function anchorSlug(heading) {
  if (heading.startsWith('^')) return heading
  let out = ''
  for (const ch of heading.trim().toLowerCase()) {
    if (ch === ' ') out += '-'
    else if (KEPT.test(ch)) out += ch
  }
  return out
}

// Same patterns core uses to enumerate anchors (extract.py): ATX headings and trailing block ids.
const HEADING = /^(#{1,6})[ \t]+(.+?)[ \t#]*$/
const BLOCK_ID = /(?:^|\s)(\^[A-Za-z0-9-]+)\s*$/

/** Headings of a Markdown body as {line (1-based), level, text, anchor}. Fences are not special, as in core. */
export function scanHeadings(markdown) {
  const out = []
  markdown.split('\n').forEach((text, i) => {
    const m = HEADING.exec(text)
    if (m) out.push({ line: i + 1, level: m[1].length, text: m[2], anchor: anchorSlug(m[2]) })
  })
  return out
}

/** '^block-id' anchors with their 1-based line. */
export function scanBlockIds(markdown) {
  const out = []
  markdown.split('\n').forEach((text, i) => {
    const m = BLOCK_ID.exec(text)
    if (m) out.push({ line: i + 1, anchor: m[1] })
  })
  return out
}
