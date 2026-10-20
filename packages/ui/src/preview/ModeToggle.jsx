// 'Live preview | Source' (EditorDesk). A pair of toggle buttons in a labelled group. Given the editor's
// view it switches the layer itself; the host keeps the mode in its own state through `mode` / `onChange`.
import { useState } from 'react'
import { switchPreviewMode } from './livePreview.js'
import { mergePreviewStrings } from './strings.js'
import { styles as s } from './styles.js'

/**
 * @param {object} props
 * @param {import('@codemirror/view').EditorView|null} [props.view]  The editor (NoteEditor's onReady). When given, a click switches its live-preview layer.
 * @param {'preview'|'source'} [props.mode]  Controlled mode. Without it the toggle keeps its own, starting at `defaultMode`.
 * @param {'preview'|'source'} [props.defaultMode]
 * @param {(mode: 'preview'|'source') => void} [props.onChange]
 * @param {object} [props.strings]  Copy overrides (see PREVIEW_STRINGS).
 */
export function ModeToggle({ view, mode, defaultMode = 'preview', onChange, strings: overrides }) {
  const strings = mergePreviewStrings(overrides)
  const [own, setOwn] = useState(defaultMode)
  const current = mode ?? own

  const choose = (next) => {
    if (view) switchPreviewMode(view, next)
    if (mode === undefined) setOwn(next)
    onChange?.(next)
  }

  const segment = (value, label) => (
    <button
      type="button"
      style={current === value ? s.segmentOn : s.segment}
      aria-pressed={current === value}
      data-mode={value}
      // The editor keeps its caret and its keyboard.
      onMouseDown={(event) => event.preventDefault()}
      onClick={() => choose(value)}
    >
      {label}
    </button>
  )

  return (
    <div role="group" aria-label={strings.modeGroup} style={s.toggle} data-arpn="mode-toggle">
      {segment('preview', strings.livePreview)}
      {segment('source', strings.source)}
    </div>
  )
}
