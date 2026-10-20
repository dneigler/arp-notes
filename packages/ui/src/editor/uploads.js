// Paste/drop upload (spike §2.3 / §4.3): EditorView.domEventHandlers paste + drop. A file is checked
// against capabilities (attachments on, MIME, size) before anything is sent; then an in-document
// placeholder `![uploading name…](attachment://pending-x)` goes in at the cursor or drop point, and is
// swapped for `![name](attachment://<blob_id>)` when the host's `upload` resolves. The editor never talks
// to the network itself: `upload(file, {onProgress}) -> {blob_id, filename}` is the host's.
import { Transaction } from '@codemirror/state'
import { EditorView } from '@codemirror/view'
import { checkFile } from './policy.js'
import { PENDING_PREFIX } from './scan.js'

let counter = 0

function pendingId() {
  counter += 1
  return `${PENDING_PREFIX}${Date.now().toString(36)}${counter.toString(36)}${Math.random().toString(36).slice(2, 6)}`
}

/** Markdown link text cannot hold brackets or line breaks. */
const altText = (name) => String(name).replace(/[[\]\r\n]+/g, ' ').replace(/\s+/g, ' ').trim()

function placeholderRegex(id) {
  return new RegExp(`!?\\[[^\\]\\n]*\\]\\(attachment:\\/\\/${id}\\)`)
}

function progressOf(file, p) {
  if (typeof p === 'number') return { loaded: Math.round(p * file.size), total: file.size, fraction: p }
  const total = p?.total || file.size || 0
  const loaded = p?.loaded ?? 0
  return { loaded, total, fraction: p?.fraction ?? (total ? loaded / total : 0) }
}

/**
 * @param {object} options
 * @param {() => EditorView|null} options.getView
 * @param {() => object|undefined} options.getCapabilities
 * @param {() => Function|undefined} options.getUpload
 * @param {(uploads: Array<object>) => void} options.onUploads  Every change to the in-flight list.
 * @param {(rejection: {reason: 'off'|'type'|'size', file?: File}) => void} options.onReject  A file was left out.
 */
export function createUploadController({ getView, getCapabilities, getUpload, onUploads, onReject }) {
  const uploads = new Map()
  const publish = () => onUploads([...uploads.values()])

  function swap(id, replacement) {
    const view = getView()
    if (!view) return
    const m = placeholderRegex(id).exec(view.state.doc.toString())
    // The writer deleted the placeholder while the bytes travelled: nothing to put back.
    if (!m) return
    view.dispatch({
      changes: { from: m.index, to: m.index + m[0].length, insert: replacement },
      // Not an edit the writer would want to undo on its own.
      annotations: Transaction.addToHistory.of(false),
      userEvent: 'input.upload',
    })
  }

  async function start(entry, file, upload) {
    try {
      const result = await upload(file, {
        onProgress: (p) => {
          const current = uploads.get(entry.id)
          if (!current) return
          Object.assign(current, progressOf(file, p))
          publish()
        },
      })
      uploads.delete(entry.id)
      const name = altText(result?.filename || file.name)
      swap(entry.id, `${entry.image ? '!' : ''}[${name}](attachment://${result.blob_id})`)
    } catch (error) {
      const current = uploads.get(entry.id)
      if (current) {
        current.state = 'error'
        current.error = error instanceof Error ? error.message : String(error)
      }
      swap(entry.id, '')
    }
    publish()
  }

  /**
   * Handle files pasted or dropped at `range`. Returns true when the event was ours (files were present),
   * so the caller cancels the browser's default.
   */
  function handleFiles(files, range) {
    if (!files.length) return false
    const view = getView()
    const capabilities = getCapabilities()
    const upload = getUpload()
    if (!view) return true
    if (!capabilities?.attachments || typeof upload !== 'function') {
      onReject({ reason: 'off', file: files[0] })
      return true
    }

    const accepted = []
    let rejection = null
    for (const file of files) {
      const problem = checkFile(file, capabilities)
      if (problem) rejection ??= { ...problem, file }
      else accepted.push(file)
    }
    if (rejection) onReject(rejection)
    if (!accepted.length) return true

    const entries = accepted.map((file) => {
      const image = (file.type || '').startsWith('image/')
      const id = pendingId()
      return {
        entry: { id, name: file.name, image, size: file.size, loaded: 0, total: file.size, fraction: 0, state: 'uploading', error: null },
        file,
        text: `${image ? '!' : ''}[uploading ${altText(file.name)}…](attachment://${id})`,
      }
    })
    const insert = entries.map((e) => e.text).join(view.state.lineBreak)
    const doc = view.state.doc
    const from = Math.min(range.from, doc.length)
    const to = Math.min(range.to, doc.length)
    view.dispatch({
      changes: { from, to, insert },
      selection: { anchor: from + insert.length },
      userEvent: 'input.paste',
      scrollIntoView: true,
    })
    for (const { entry } of entries) uploads.set(entry.id, entry)
    publish()
    for (const { entry, file } of entries) void start(entry, file, upload)
    return true
  }

  return {
    handleFiles,
    /** Forget a failed upload's row ('Dismiss'). */
    dismiss(id) {
      if (uploads.delete(id)) publish()
    },
    get active() {
      return [...uploads.values()]
    },
  }
}

function filesOf(dataTransfer) {
  return dataTransfer?.files ? Array.from(dataTransfer.files) : []
}

/** The paste + drop handlers, wired to a controller. */
export function uploadHandlers(controller) {
  return EditorView.domEventHandlers({
    paste(event, view) {
      const files = filesOf(event.clipboardData)
      // Files copied together with text (a Finder copy, a Word paste) are a text paste. A screenshot or
      // a copied image carries no text, and that is the paste this handles.
      if (!files.length || event.clipboardData.getData('text/plain').trim()) return false
      event.preventDefault()
      return controller.handleFiles(files, view.state.selection.main)
    },
    drop(event, view) {
      const files = filesOf(event.dataTransfer)
      if (!files.length) return false
      event.preventDefault()
      const pos = view.posAtCoords({ x: event.clientX, y: event.clientY }) ?? view.state.selection.main.head
      return controller.handleFiles(files, { from: pos, to: pos })
    },
  })
}
