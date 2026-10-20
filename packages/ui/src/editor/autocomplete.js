// `[[` autocomplete (spike §2.2 / §4.3): a @codemirror/autocomplete source that asks every host scheme to
// search, lists typed rows (Piece / Movement / Composer) and, on Enter, replaces `[[q` with the house
// chip `[@Title](prefix://type/id)`. Esc closes the popover and leaves the typed text as it is.
import { completionStatus } from '@codemirror/autocomplete'
import { ViewPlugin } from '@codemirror/view'

const OPEN = /\[\[[^\]]*$/
const MAX_ROWS = 10

const encode = (value) => encodeURIComponent(String(value))

/** Brackets and line breaks would end the link text early, so they cannot go in a chip label. */
export function chipLabel(label) {
  return String(label).replace(/\[/g, '(').replace(/\]/g, ')').replace(/\s*[\r\n]+\s*/g, ' ').trim()
}

/** `[@Title](prefix://entity_type/id)` for a search candidate of `scheme` (K§4, K§12.2). */
export function chipText(scheme, candidate) {
  const label = chipLabel(candidate.entity_label ?? candidate.title ?? candidate.entity_id)
  return `[@${label}](${scheme.prefix}://${encode(candidate.entity_type)}/${encode(candidate.entity_id)})`
}

function typeLabel(type, strings) {
  const known = strings.entityTypes[type]
  if (known) return known
  const text = String(type).replace(/[_-]+/g, ' ')
  return text.charAt(0).toUpperCase() + text.slice(1)
}

/** The text typed after `[[` before the cursor, or null when the cursor is not inside an open `[[`. */
export function wikiQuery(state) {
  const head = state.selection.main.head
  const line = state.doc.lineAt(head)
  const m = OPEN.exec(state.sliceDoc(line.from, head))
  return m ? m[0].slice(2) : null
}

/**
 * @param {object} options
 * @param {() => Array<{prefix: string, search: Function}>} options.getSchemes
 * @param {() => object} options.getStrings
 */
export function wikiLinkSource({ getSchemes, getStrings }) {
  return async function wikiLink(context) {
    const match = context.matchBefore(OPEN)
    if (!match) return null
    const schemes = getSchemes().filter((s) => typeof s?.search === 'function')
    if (!schemes.length) return null
    const q = match.text.slice(2)
    const strings = getStrings()

    // A scheme that throws or never answers must not hide the others.
    const lists = await Promise.all(
      schemes.map((scheme) =>
        Promise.resolve()
          .then(() => scheme.search(q))
          .then((rows) => (Array.isArray(rows) ? rows : []).map((candidate) => ({ scheme, candidate })))
          .catch(() => []),
      ),
    )
    if (context.aborted) return null

    const rows = lists.flat()
    // Best first when the hosts score their rows; otherwise each host's own order.
    if (rows.every((r) => typeof r.candidate.score === 'number')) rows.sort((a, b) => b.candidate.score - a.candidate.score)
    const options = rows.slice(0, MAX_ROWS).map(({ scheme, candidate }) => {
      const text = chipText(scheme, candidate)
      const tag = typeLabel(candidate.entity_type, strings)
      return {
        label: candidate.entity_label ?? candidate.title ?? String(candidate.entity_id),
        detail: candidate.composer_label ? `${tag} · ${candidate.composer_label}` : tag,
        apply(view, _completion, from, to) {
          // `[[Cho]]` typed by hand: take the closing brackets too.
          const end = view.state.sliceDoc(to, to + 2) === ']]' ? to + 2 : to
          view.dispatch({
            changes: { from, to: end, insert: text },
            selection: { anchor: from + text.length },
            userEvent: 'input.complete',
          })
        },
      }
    })
    if (!options.length) return null
    // filter:false — the hosts already searched; CodeMirror's own fuzzy match would drop every row,
    // because the typed text begins with '[['. No validFor, so each keystroke asks again.
    return { from: match.from, filter: false, options }
  }
}

/**
 * The popover's title ('Link to · “q”') and key hint, added to CodeMirror's tooltip once it is on screen.
 * CodeMirror has no header or footer slot, so this adds two elements of its own beside the list.
 */
export function popoverChrome(getStrings) {
  return ViewPlugin.fromClass(
    class {
      constructor(view) {
        this.view = view
      }

      update(update) {
        if (completionStatus(update.state) !== 'active') return
        const view = update.view
        view.requestMeasure({
          read: () => view.dom.querySelector('.cm-tooltip-autocomplete'),
          write: (tip) => {
            if (!tip) return
            const strings = getStrings()
            const q = wikiQuery(view.state)
            let head = tip.querySelector(':scope > .arpn-wiki-head')
            if (!head) {
              head = document.createElement('div')
              head.className = 'arpn-wiki-head'
              tip.prepend(head)
              const hint = document.createElement('div')
              hint.className = 'arpn-wiki-hint'
              hint.textContent = strings.linkHint
              tip.append(hint)
            }
            if (q !== null) head.textContent = strings.linkTo(q)
          },
        })
      }
    },
  )
}
