// What the toolbar buttons do to the document: plain Markdown edits, nothing else. Each command takes the
// EditorView, returns true, and leaves focus in the editor so a tap on a button never closes the keyboard.
import { startCompletion } from '@codemirror/autocomplete'
import { EditorSelection } from '@codemirror/state'

const HEADING = '## '
const BULLET = '- '
const HEADING_PREFIX = /^#{1,6}[ \t]+/
const LIST_ITEM = /^([ \t]*)([-*+])[ \t]+/

function finish(view, spec) {
  view.dispatch({ ...spec, scrollIntoView: true, userEvent: 'input.format' })
  view.focus()
  return true
}

/** The lines a selection touches. A selection that ends at the very start of a line has not reached it. */
function selectedLines(state) {
  const { from, to, empty } = state.selection.main
  const first = state.doc.lineAt(from)
  let last = state.doc.lineAt(to)
  if (!empty && to === last.from && last.number > first.number) last = state.doc.line(last.number - 1)
  const lines = []
  for (let n = first.number; n <= last.number; n += 1) lines.push(state.doc.line(n))
  return lines
}

/** Apply per-line edits and keep the selection where the text it covered went. */
function editLines(view, edits) {
  const changes = view.state.changes(edits)
  return finish(view, { changes, selection: view.state.selection.map(changes, 1) })
}

/** Heading: `## ` at the start of the line, or taken off when the line already has it. Other levels become `## `. */
export function toggleHeading(view) {
  const lines = selectedLines(view.state)
  const off = lines.every((line) => line.text.startsWith(HEADING))
  return editLines(
    view,
    lines.map((line) => {
      const current = HEADING_PREFIX.exec(line.text)
      return {
        from: line.from,
        to: line.from + (current ? current[0].length : 0),
        insert: off ? '' : HEADING,
      }
    }),
  )
}

/** Bulleted list: `- ` after the indentation of every selected line, or taken off when they all have one. */
export function toggleBulletList(view) {
  const all = selectedLines(view.state)
  // Blank lines inside a multi-line selection stay blank.
  const lines = all.length > 1 ? all.filter((line) => line.text.trim()) : all
  if (!lines.length) return finish(view, {})
  const off = lines.every((line) => LIST_ITEM.test(line.text))
  return editLines(
    view,
    lines.flatMap((line) => {
      const item = LIST_ITEM.exec(line.text)
      if (off) return [{ from: line.from + item[1].length, to: line.from + item[0].length, insert: '' }]
      if (item) return []
      const indent = /^[ \t]*/.exec(line.text)[0].length
      return [{ from: line.from + indent, insert: BULLET }]
    }),
  )
}

function runLength(text, step) {
  let n = 0
  while (n < text.length && text[step > 0 ? n : text.length - 1 - n] === '*') n += 1
  return n
}

/**
 * Does a run of `n` asterisks around a span mean `mark` is on? `*` is italic, `**` bold, `***` both: italic
 * needs an odd run, bold needs at least two.
 */
function isOn(mark, n) {
  return mark.length === 1 ? n % 2 === 1 : n >= 2
}

/** Wrap the selection in `mark`, or take `mark` off when it is already around it (or inside its ends). */
function toggleWrap(view, mark) {
  const { state } = view
  const m = mark.length
  const asterisks = mark[0] === '*'
  const spec = state.changeByRange((range) => {
    let { from, to } = range
    if (range.empty) {
      // A caret inside a word marks the word; between spaces it opens an empty pair.
      const word = state.wordAt(from)
      if (word) ({ from, to } = word)
    }
    const text = state.sliceDoc(from, to)
    const before = state.sliceDoc(Math.max(0, from - 3), from)
    const after = state.sliceDoc(to, to + 3)

    // The marks sit just outside: **word** with "word" selected.
    const around = Math.min(runLength(before, -1), runLength(after, 1))
    if (asterisks ? isOn(mark, around) : before.endsWith(mark) && after.startsWith(mark)) {
      return {
        changes: [{ from: from - m, to: from }, { from: to, to: to + m }],
        range: EditorSelection.range(range.anchor - m, range.head - m),
      }
    }
    // The marks are inside the selection: "**word**" selected.
    const inside = Math.min(runLength(text, 1), runLength(text, -1))
    if (text.length >= 2 * m + 1 && (asterisks ? isOn(mark, inside) : text.startsWith(mark) && text.endsWith(mark))) {
      return {
        changes: [{ from, to: from + m }, { from: to - m, to }],
        range: range.anchor <= range.head ? EditorSelection.range(from, to - 2 * m) : EditorSelection.range(to - 2 * m, from),
      }
    }
    if (from === to) {
      return { changes: { from, insert: mark + mark }, range: EditorSelection.cursor(from + m) }
    }
    return {
      changes: [{ from, insert: mark }, { from: to, insert: mark }],
      range: EditorSelection.range(range.anchor + m, range.head + m),
    }
  })
  return finish(view, spec)
}

/** Bold: `**` around the selection (or the word at the caret). */
export const toggleBold = (view) => toggleWrap(view, '**')
/** Italic: `*` around the selection (or the word at the caret). */
export const toggleItalic = (view) => toggleWrap(view, '*')

/** Link: types `[[` at the caret (before a selection, which becomes the search) and opens the autocomplete. */
export function insertWikiLink(view) {
  const { from, to } = view.state.selection.main
  view.dispatch({
    changes: { from, insert: '[[' },
    selection: { anchor: to + 2 },
    scrollIntoView: true,
    userEvent: 'input.type',
  })
  view.focus()
  startCompletion(view)
  return true
}

/**
 * Image: hands the picked files to the editor's own paste path, the one C6d's upload controller listens on, so
 * the attachment policy, the placeholder and the progress strip behave exactly as for a pasted screenshot.
 */
export function addImageFiles(view, files) {
  const list = Array.from(files ?? [])
  if (!list.length) return false
  const event = new Event('paste', { bubbles: true, cancelable: true })
  Object.defineProperty(event, 'clipboardData', {
    value: { files: list, items: [], types: ['Files'], getData: () => '' },
  })
  view.contentDOM.dispatchEvent(event)
  view.focus()
  return true
}
