// The framework-free part of NoteEditor: the CodeMirror extension set and a state factory. NoteEditor.jsx
// (React) mounts it; tests and the C6e live-preview layer can use it directly.
import { autocompletion } from '@codemirror/autocomplete'
import { defaultKeymap, history, historyKeymap } from '@codemirror/commands'
import { Annotation, Compartment, EditorState } from '@codemirror/state'
import { EditorView, drawSelection, highlightActiveLine, keymap } from '@codemirror/view'
import { popoverChrome, wikiLinkSource } from './autocomplete.js'
import { chipExtension } from './chips.js'
import { markdownLanguage, markdownStyle } from './markdown.js'
import { editorTheme } from './theme.js'
import { uploadHandlers } from './uploads.js'

/** Marks a transaction that applies the host's `value` rather than a keystroke: no onChange, no undo step. */
export const External = Annotation.define()

/** Compartments NoteEditor reconfigures when a prop changes. */
export function createCompartments() {
  return { attributes: new Compartment(), extra: new Compartment() }
}

/** aria-label and friends for the contenteditable. */
export function contentAttributes(ariaLabel) {
  return EditorView.contentAttributes.of({ 'aria-label': ariaLabel, spellcheck: 'true', autocapitalize: 'sentences' })
}

/**
 * @param {object} ctx
 * @param {() => Array<object>} ctx.getSchemes
 * @param {() => object} ctx.getStrings
 * @param {object} ctx.uploads  createUploadController(...)
 * @param {(update: import('@codemirror/view').ViewUpdate) => void} ctx.onUpdate
 * @param {ReturnType<typeof createCompartments>} ctx.compartments
 * @param {string} ctx.ariaLabel
 * @param {Array} [ctx.extra]  Host extensions (C6e's livePreview(), a toolbar's keymap, ...).
 */
export function editorExtensions({ getSchemes, getStrings, uploads, onUpdate, compartments, ariaLabel, extra = [] }) {
  return [
    history(),
    drawSelection(),
    highlightActiveLine(),
    EditorView.lineWrapping,
    markdownLanguage.extension,
    markdownStyle,
    chipExtension(getSchemes, () => getStrings().notFound),
    autocompletion({
      override: [wikiLinkSource({ getSchemes, getStrings })],
      icons: false,
      closeOnBlur: true,
      selectOnOpen: true,
      maxRenderedOptions: 10,
      tooltipClass: () => 'arpn-wiki-tip',
    }),
    popoverChrome(getStrings),
    uploadHandlers(uploads),
    // No Tab binding: Tab must keep moving focus out of the editor (WCAG 2.1.2).
    keymap.of([...defaultKeymap, ...historyKeymap]),
    editorTheme,
    EditorView.updateListener.of(onUpdate),
    compartments.attributes.of(contentAttributes(ariaLabel)),
    compartments.extra.of(extra),
  ]
}

/**
 * A body that uses CRLF throughout must come back with CRLF: CodeMirror normalises line breaks to \n
 * unless told otherwise, which would rewrite every line on the first save.
 */
export function lineSeparatorFor(body) {
  return /\r\n/.test(body) && !/(^|[^\r])\n/.test(body) ? ['\r\n'] : []
}

/**
 * The note body as text, with the document's own line breaks. `state.doc.toString()` always joins with \n,
 * so a CRLF body would come back changed.
 */
export function bodyOf(state) {
  return state.sliceDoc(0, state.doc.length)
}

/** The EditorState NoteEditor starts from. */
export function createEditorState(body, extensions) {
  const sep = lineSeparatorFor(body)
  return EditorState.create({
    doc: body,
    extensions: [sep.length ? EditorState.lineSeparator.of(sep[0]) : [], extensions],
  })
}
