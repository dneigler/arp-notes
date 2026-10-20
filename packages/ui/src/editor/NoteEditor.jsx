// NoteEditor: the note body editor on CodeMirror 6 (ADR D4). The document is the Markdown string the writer
// typed, so a note round-trips byte for byte. It never fetches: the host supplies link schemes, an upload
// function and autosave callbacks, and reads status back through onStatus (K§8).
import { Transaction } from '@codemirror/state'
import { EditorView } from '@codemirror/view'
import { useEffect, useMemo, useRef, useState } from 'react'
import { formatUploadProgress } from '../api/progress.js'
import { createAutosaver } from './autosave.js'
import { refreshChips } from './chips.js'
import {
  External,
  bodyOf,
  contentAttributes,
  createCompartments,
  createEditorState,
  editorExtensions,
} from './core.js'
import { PolicyDialog } from './PolicyDialog.jsx'
import { stripPlaceholders } from './scan.js'
import { mergeStrings } from './strings.js'
import { styles as s } from './styles.js'
import { createUploadController } from './uploads.js'

const NO_SCHEMES = []
const NO_EXTENSIONS = []
// Values we handed to onChange a moment ago can come straight back as `value`; they are not edits.
const ECHOES = 3

function UploadRow({ upload, strings, onDismiss }) {
  if (upload.state === 'error') {
    return (
      <div style={s.uploadError} data-upload="error">
        <span style={s.uploadErrorText}>
          {strings.uploadFailed(upload.name)}
          {upload.error ? ` — ${upload.error}` : ''}
        </span>
        <button type="button" style={s.link} onClick={() => onDismiss(upload.id)}>
          {strings.dismiss}
        </button>
      </div>
    )
  }
  const percent = Math.round(upload.fraction * 100)
  return (
    <div style={s.upload} data-upload="uploading">
      <div style={s.uploadHead}>{strings.uploading(upload.name)}</div>
      <div
        style={s.track}
        role="progressbar"
        aria-label={strings.uploading(upload.name)}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={percent}
      >
        <div style={s.fill(upload.fraction)} />
      </div>
      <div style={s.uploadMeta}>{formatUploadProgress(upload)}</div>
      <div style={s.uploadMeta}>{strings.keepTyping}</div>
    </div>
  )
}

/**
 * @param {object} props
 * @param {string} props.value  The note body (Markdown). A `value` that differs from the text in the editor
 *   and is not an echo of onChange replaces it (a conflict answered with the server's copy, for example).
 * @param {(body: string) => void} [props.onChange]  Every edit, with the whole body.
 * @param {Array<{prefix: string, search: (q: string) => Array|Promise<Array>, resolve: (type: string, id: number|string) => object|null|Promise<object|null>}>} [props.schemes]
 *   Host link schemes (K§12.2, bound to the user by the host). `search` returns candidates
 *   {entity_type, entity_id, entity_label, composer_label?, score?}; `resolve` returns {title, url?} or null.
 * @param {(file: File, opts: {onProgress: (p: {loaded: number, total: number}|number) => void}) => Promise<{blob_id: number|string, filename: string}>} [props.upload]
 *   Sends one file. Without it, or with capabilities.attachments false, a pasted or dropped file is left out
 *   and the 'Image not added' dialog explains why.
 * @param {object} [props.capabilities]  GET /notes/capabilities. Drives the attachment policy.
 * @param {{save: (body_md: string, version: number) => Promise<object>, version: number, onConflict?: (server: object) => void}} [props.autosave]
 *   Autosave, debounced 1.5 s. `save` resolves to the house envelope {note} | {conflict: true, server_version, server_data};
 *   a conflict calls onConflict with that whole envelope and pauses until `version` or `value` changes.
 * @param {(status: {save: 'idle'|'dirty'|'saving'|'saved'|'conflict'|'error', version: number|null, uploads: Array<object>}) => void} [props.onStatus]
 *   Autosave state and the uploads in flight; pass `status.uploads` to EditorRail.
 * @param {string} [props.ariaLabel]
 * @param {Array} [props.extensions]  Extra CodeMirror extensions (the live-preview layer, a toolbar keymap).
 * @param {(view: EditorView|null) => void} [props.onReady]  The EditorView once mounted; null when it is torn down.
 * @param {object} [props.strings]  Copy overrides (see EDITOR_STRINGS).
 */
export function NoteEditor({
  value = '',
  onChange,
  schemes = NO_SCHEMES,
  upload,
  capabilities,
  autosave,
  onStatus,
  ariaLabel = 'Note',
  extensions = NO_EXTENSIONS,
  onReady,
  strings: stringOverrides,
  minHeight,
  className,
}) {
  const strings = useMemo(() => mergeStrings(stringOverrides), [stringOverrides])
  const hostRef = useRef(null)
  const viewRef = useRef(null)
  const autosaverRef = useRef(null)
  const compartmentsRef = useRef(null)
  const echoes = useRef([])
  const [uploads, setUploads] = useState([])
  const [saveState, setSaveState] = useState('idle')
  const [rejection, setRejection] = useState(null)
  const controllerRef = useRef(null)

  // Everything the long-lived CodeMirror callbacks read, always current.
  const live = useRef({})
  live.current = { value, onChange, schemes, upload, capabilities, autosave, onStatus, onReady, strings, ariaLabel, extensions }

  useEffect(() => {
    const compartments = createCompartments()
    compartmentsRef.current = compartments
    const controller = createUploadController({
      getView: () => viewRef.current,
      getCapabilities: () => live.current.capabilities,
      getUpload: () => live.current.upload,
      onUploads: setUploads,
      onReject: setRejection,
    })
    controllerRef.current = controller
    const initial = live.current.value
    const autosaver = createAutosaver({
      body: stripPlaceholders(initial),
      version: live.current.autosave?.version ?? 0,
      getHandlers: () => live.current.autosave ?? { save: () => Promise.resolve({}) },
      onState: setSaveState,
    })
    autosaverRef.current = autosaver

    const state = createEditorState(
      initial,
      editorExtensions({
        getSchemes: () => live.current.schemes,
        getStrings: () => live.current.strings,
        uploads: controller,
        compartments,
        ariaLabel: live.current.ariaLabel,
        extra: live.current.extensions,
        onUpdate(update) {
          if (!update.docChanged) return
          if (update.transactions.some((tr) => tr.annotation(External))) return
          const body = bodyOf(update.state)
          echoes.current = [body, ...echoes.current].slice(0, ECHOES)
          live.current.onChange?.(body)
          if (live.current.autosave) autosaver.edit(stripPlaceholders(body))
        },
      }),
    )
    const view = new EditorView({ state, parent: hostRef.current })
    viewRef.current = view
    live.current.onReady?.(view)

    return () => {
      if (live.current.autosave) autosaver.flush()
      autosaver.dispose()
      live.current.onReady?.(null)
      view.destroy()
      viewRef.current = null
    }
  }, [])

  // The host replaced the body.
  useEffect(() => {
    const view = viewRef.current
    if (!view) return
    if (value === bodyOf(view.state) || echoes.current.includes(value)) return
    view.dispatch({
      changes: { from: 0, to: view.state.doc.length, insert: value },
      annotations: [External.of(true), Transaction.addToHistory.of(false)],
    })
    echoes.current = []
    autosaverRef.current?.reset(stripPlaceholders(value), live.current.autosave?.version)
  }, [value])

  // The host answered a conflict, or moved the version on.
  useEffect(() => {
    if (typeof autosave?.version === 'number') autosaverRef.current?.setVersion(autosave.version)
  }, [autosave?.version])

  useEffect(() => {
    viewRef.current?.dispatch({ effects: refreshChips.of(null) })
  }, [schemes])

  useEffect(() => {
    viewRef.current?.dispatch({ effects: compartmentsRef.current.attributes.reconfigure(contentAttributes(ariaLabel)) })
  }, [ariaLabel])

  useEffect(() => {
    viewRef.current?.dispatch({ effects: compartmentsRef.current.extra.reconfigure(extensions) })
  }, [extensions])

  useEffect(() => {
    live.current.onStatus?.({ save: saveState, version: autosaverRef.current?.version ?? null, uploads })
  }, [saveState, uploads])

  const saveText = autosave ? strings.saveStates[saveState] : ''
  const rootStyle = minHeight ? { ...s.root, '--arpn-editor-min-height': typeof minHeight === 'number' ? `${minHeight}px` : minHeight } : s.root

  return (
    <div style={rootStyle} className={className} data-arpn="note-editor" data-save={saveState}>
      <div ref={hostRef} />
      <div style={s.uploads} role="status" aria-live="polite">
        {uploads.map((u) => (
          <UploadRow key={u.id} upload={u} strings={strings} onDismiss={(id) => controllerRef.current?.dismiss(id)} />
        ))}
      </div>
      {autosave ? (
        <div style={s.status} role="status" aria-live="polite" data-arpn="save-status">
          {saveText}
        </div>
      ) : null}
      {rejection ? (
        <PolicyDialog rejection={rejection} capabilities={capabilities} strings={strings} onClose={() => setRejection(null)} />
      ) : null}
    </div>
  )
}
