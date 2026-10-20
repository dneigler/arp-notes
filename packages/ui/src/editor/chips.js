// Host link chips in the editor (spike §2.2 / §4.3): a ViewPlugin that draws each `[@Title](prefix://type/id)`
// span as a Decoration.replace widget, resolved asynchronously through the scheme's `resolve` with a
// cache. The source text is never changed. When the cursor is inside a span the source shows instead,
// as in Obsidian's live preview, so the chip can be edited. A chip the host cannot resolve keeps its text
// and reads '<text> · not found' (K§4, EditorDesk).
import { ensureSyntaxTree } from '@codemirror/language'
import { StateEffect } from '@codemirror/state'
import { Decoration, ViewPlugin, WidgetType } from '@codemirror/view'
import { findChips, inCode } from './scan.js'

/** Dispatch to redraw every chip, for example after the `schemes` prop changed. */
export const refreshChips = StateEffect.define()

// scheme object -> Map<'type/id', entry>. An entry's `value` is set once the host answers, so a widget
// rebuilt later paints at once instead of flashing the unresolved text again.
const caches = new WeakMap()

/**
 * The resolve result for one chip, cached per scheme.
 * @returns {{promise: Promise<{found: boolean, title?: string, url?: string}>, value: null|{found: boolean, title?: string, url?: string}}}
 */
export function chipEntry(scheme, entityType, entityId) {
  let entries = caches.get(scheme)
  if (!entries) caches.set(scheme, (entries = new Map()))
  const key = `${entityType}/${entityId}`
  let entry = entries.get(key)
  if (!entry) {
    entry = { value: null, promise: null }
    entry.promise = Promise.resolve()
      .then(() => scheme.resolve(entityType, entityId))
      .then(
        (result) => (result && typeof result === 'object' ? { found: true, title: result.title, url: result.url } : { found: false }),
        () => {
          entries.delete(key) // a host error is not an answer: ask again next time
          return { found: false, failed: true }
        },
      )
      .then((value) => (entry.value = value))
    entries.set(key, entry)
  }
  return entry
}

class ChipWidget extends WidgetType {
  constructor(chip, entry, notFound) {
    super()
    this.chip = chip
    this.entry = entry
    this.notFound = notFound
  }

  eq(other) {
    return other.chip.raw === this.chip.raw && other.entry === this.entry && other.notFound === this.notFound
  }

  paint(dom) {
    const { label, prefix, entityType, entityId } = this.chip
    const value = this.entry.value
    const state = !value ? 'pending' : value.found ? 'found' : 'missing'
    dom.dataset.state = state
    dom.title = `${prefix}://${entityType}/${entityId}`
    if (state === 'found') dom.textContent = `@${value.title || label}`
    else if (state === 'missing') dom.textContent = `@${label} · ${this.notFound}`
    else dom.textContent = `@${label}`
  }

  toDOM(view) {
    const dom = document.createElement('span')
    dom.className = 'arpn-chip'
    dom.dataset.prefix = this.chip.prefix
    dom.dataset.entityType = this.chip.entityType
    dom.dataset.entityId = String(this.chip.entityId)
    this.paint(dom)
    if (!this.entry.value) this.entry.promise.then(() => this.paint(dom))
    // A click puts the cursor inside the span, which shows its source for editing.
    dom.addEventListener('mousedown', (event) => {
      event.preventDefault()
      const from = view.posAtDOM(dom)
      view.dispatch({ selection: { anchor: Math.min(from + 2, view.state.doc.length) } })
      view.focus()
    })
    return dom
  }

  ignoreEvent() {
    return true
  }
}

/**
 * @param {() => Array<object>} getSchemes  The editor's current `schemes` prop.
 * @param {() => string} getNotFound  The 'not found' word.
 */
export function chipExtension(getSchemes, getNotFound) {
  class ChipPlugin {
    constructor(view) {
      this.decorations = this.build(view)
    }

    update(update) {
      if (
        update.docChanged ||
        update.viewportChanged ||
        update.selectionSet ||
        update.transactions.some((tr) => tr.effects.some((e) => e.is(refreshChips)))
      ) {
        this.decorations = this.build(update.view)
      }
    }

    build(view) {
      const schemes = getSchemes()
      if (!schemes.length) return Decoration.none
      const { state } = view
      const notFound = getNotFound()
      const ranges = view.visibleRanges.length ? view.visibleRanges : [view.viewport]
      const marks = []
      let covered = -1
      for (const range of ranges) {
        const start = state.doc.lineAt(range.from).from
        const end = state.doc.lineAt(range.to).to
        const text = state.doc.sliceString(start, end)
        if (!text.includes('](')) continue
        const tree = ensureSyntaxTree(state, end, 25)
        const chips = findChips(text, schemes, {
          offset: start,
          isCode: tree ? (i) => inCode(tree, start + i) : undefined,
        })
        for (const chip of chips) {
          if (chip.from < covered) continue
          covered = chip.to
          const inside = state.selection.ranges.some((r) => r.head > chip.from && r.head < chip.to)
          if (inside) continue
          const entry = chipEntry(chip.scheme, chip.entityType, chip.entityId)
          marks.push(Decoration.replace({ widget: new ChipWidget(chip, entry, notFound) }).range(chip.from, chip.to))
        }
      }
      return Decoration.set(marks)
    }
  }
  return ViewPlugin.fromClass(ChipPlugin, { decorations: (plugin) => plugin.decorations })
}
