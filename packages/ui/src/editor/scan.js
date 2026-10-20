// Pure scans over a note body: host link chips and attachment images. The editor's chip plugin, the
// rail and the tests all read the same regexes, so what the rail counts is what the editor draws.
import { parser } from '@lezer/markdown'

const escapeRe = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')

/**
 * The house chip form `[@Title](prefix://entity_type/id)` (K§4), one regex per scheme. Groups: 1 label
 * (without the '@'), 2 entity_type, 3 id. A new RegExp each call, so `lastIndex` is never shared.
 */
export function chipRegex(prefix, flags = 'gi') {
  return new RegExp(`\\[@([^\\]\\n]*)\\]\\(${escapeRe(prefix)}:\\/\\/([^/)\\s]+)\\/([^)\\s]+)\\)`, flags)
}

function decode(value) {
  try {
    return decodeURIComponent(value)
  } catch {
    return value
  }
}

/** Ids reach `resolve(type, id)` the way NoteBody passes them: digits as numbers, anything else as written. */
function idFrom(raw) {
  const id = decode(raw)
  return /^\d+$/.test(id) ? Number(id) : id
}

const CODE_NODES = new Set([
  'FencedCode',
  'CodeBlock',
  'InlineCode',
  'HTMLBlock',
  'CommentBlock',
  'ProcessingInstructionBlock',
  'Comment',
])

/** True when `pos` sits inside code or raw HTML in a Lezer Markdown tree: a chip there is just text. */
export function inCode(tree, pos) {
  for (let node = tree.resolveInner(pos, 1); node; node = node.parent) {
    if (CODE_NODES.has(node.name)) return true
  }
  return false
}

/**
 * Chips in `text`, in document order. `schemes` is the editor's `schemes` prop ({prefix, ...}).
 * `isCode(index)` (index into `text`) lets a caller with a syntax tree drop chips inside code;
 * `offset` is added to every position so a slice of a document reports document positions.
 * @returns {Array<{from: number, to: number, raw: string, label: string, prefix: string, scheme: object, entityType: string, entityId: number|string}>}
 */
export function findChips(text, schemes, { offset = 0, isCode } = {}) {
  const found = []
  for (const scheme of schemes) {
    if (!scheme?.prefix) continue
    const re = chipRegex(scheme.prefix)
    for (let m = re.exec(text); m; m = re.exec(text)) {
      if (isCode?.(m.index)) continue
      found.push({
        from: offset + m.index,
        to: offset + m.index + m[0].length,
        raw: m[0],
        label: m[1],
        prefix: scheme.prefix,
        scheme,
        entityType: decode(m[2]),
        entityId: idFrom(m[3]),
      })
    }
  }
  return found.sort((a, b) => a.from - b.from)
}

/** Chips in a whole body, code excluded (parsed with Lezer Markdown). */
export function chipsInBody(body, schemes) {
  if (!schemes?.length || !body.includes('](')) return []
  const tree = parser.parse(body)
  return findChips(body, schemes, { isCode: (i) => inCode(tree, i) })
}

// ![name](attachment://id) is an image; [name](attachment://id) is any other file. 'pending-…' ids are
// upload placeholders (the bytes have not landed yet).
const ATTACHMENT = /(!?)\[([^\]\n]*)\]\(attachment:\/\/([^)\s]+)\)/g
export const PENDING_PREFIX = 'pending-'

/** Attachment references in a body: `{name, id, image, pending, from, to}`. Code excluded. */
export function attachmentsInBody(body) {
  if (!body.includes('attachment://')) return []
  const tree = parser.parse(body)
  const found = []
  const re = new RegExp(ATTACHMENT.source, 'g')
  for (let m = re.exec(body); m; m = re.exec(body)) {
    if (inCode(tree, m.index)) continue
    found.push({
      from: m.index,
      to: m.index + m[0].length,
      image: m[1] === '!',
      name: m[2],
      id: m[3],
      pending: m[3].startsWith(PENDING_PREFIX),
    })
  }
  return found
}

/** The upload placeholders still in a body. */
const PLACEHOLDER = new RegExp(`!?\\[[^\\]\\n]*\\]\\(attachment:\\/\\/${PENDING_PREFIX}[A-Za-z0-9]+\\)`, 'g')

/**
 * What autosave sends: the body without in-flight upload placeholders, so a closed tab never leaves a
 * `![uploading …](attachment://pending-x)` line behind. The editor's own text keeps them.
 */
export function stripPlaceholders(body) {
  return body.includes(`attachment://${PENDING_PREFIX}`) ? body.replace(PLACEHOLDER, '') : body
}
