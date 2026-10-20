// livePreview(): the CodeMirror 6 extension that makes the source editor read like a note (ADR D4, "what it
// costs"). Heading lines are sized by level, Markdown markers are dimmed away from the cursor line, the
// cursor line is banded, and image embeds draw as images. It only decorates: the document is the string the
// writer typed, with the layer on or off. Source mode is the same editor with the layer switched off, so the
// selection and the undo history survive the switch.
import { syntaxTree } from '@codemirror/language'
import { StateEffect, StateField } from '@codemirror/state'
import { Decoration, ViewPlugin } from '@codemirror/view'
import { previewDecorations } from './decorations.js'
import { createImageCache, imageWidgetFactory } from './images.js'
import { mergePreviewStrings } from './strings.js'
import { previewTheme } from './theme.js'

/** Dispatch `setPreviewMode.of('source' | 'preview')` to switch the layer. */
export const setPreviewMode = StateEffect.define()
/** Dispatch `refreshPreview.of(null)` to ask the host for every image URL again (signed URLs were renewed). */
export const refreshPreview = StateEffect.define()

const modeField = StateField.define({
  create: () => 'preview',
  update(mode, tr) {
    for (const effect of tr.effects) if (effect.is(setPreviewMode)) return effect.value === 'source' ? 'source' : 'preview'
    return mode
  },
})

/** 'preview' or 'source' for a state that has the layer; 'source' for one that does not. */
export function previewModeOf(state) {
  return state.field(modeField, false) ?? 'source'
}

/** Switch a mounted editor between 'preview' and 'source'. */
export function switchPreviewMode(view, mode) {
  if (previewModeOf(view.state) !== mode) view.dispatch({ effects: setPreviewMode.of(mode) })
}

/**
 * @param {object} [options]
 * @param {(image: {kind: 'attachment'|'embed', text: string, target: string, id?: string, alt: string, width?: number, height?: number}) => string|null|Promise<string|null>} [options.resolveAttachment]
 *   The URL for an image reference. `text` is the exact Markdown (`![name](attachment://41)`,
 *   `![[Howat.png|438x282]]`), `target` the part a host looks up (`attachment://41`, `Howat.png`). Without it
 *   images stay Markdown.
 * @param {(image: object) => void} [options.onAttachmentExpired]  An image failed to load (signed URLs last 1 h, K§8): refetch the note.
 * @param {'preview'|'source'} [options.mode]  The mode to start in. Default 'preview'.
 * @param {object} [options.strings]  Copy overrides (see PREVIEW_STRINGS).
 */
export function livePreview({ resolveAttachment, onAttachmentExpired, mode = 'preview', strings: overrides } = {}) {
  const strings = mergePreviewStrings(overrides)
  const cache = typeof resolveAttachment === 'function' ? createImageCache(resolveAttachment) : null
  const imageWidget = cache ? imageWidgetFactory(cache, { strings, onExpired: (image) => onAttachmentExpired?.(image) }) : undefined

  const plugin = ViewPlugin.fromClass(
    class {
      constructor(view) {
        this.decorations = this.build(view)
      }

      update(update) {
        const effects = update.transactions.flatMap((tr) => tr.effects)
        if (effects.some((e) => e.is(refreshPreview))) cache?.clear()
        if (
          update.docChanged ||
          update.viewportChanged ||
          update.selectionSet ||
          syntaxTree(update.state) !== syntaxTree(update.startState) ||
          effects.some((e) => e.is(setPreviewMode) || e.is(refreshPreview))
        ) {
          this.decorations = this.build(update.view)
        }
      }

      build(view) {
        if (previewModeOf(view.state) === 'source') return Decoration.none
        return previewDecorations(view.state, { ranges: view.visibleRanges, imageWidget })
      }
    },
    { decorations: (instance) => instance.decorations },
  )

  return [mode === 'source' ? modeField.init(() => 'source') : modeField, plugin, previewTheme]
}
