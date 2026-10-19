// createNotesApi: the A.6 client over the A.2 routes. Components never fetch (K§8); a host builds one
// of these and passes data and callbacks down.
import { NotesApiError } from './errors.js'
import { assertShape } from './validate.js'
import { sha256OfFile } from './sha256.js'

/** Query-string builder: drops null/undefined/'' and writes booleans as 'true'/'false'. */
export function toQuery(params = {}) {
  const qs = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === '') continue
    qs.set(key, String(value))
  }
  const text = qs.toString()
  return text ? `?${text}` : ''
}

async function readBody(res) {
  const text = await res.text().catch(() => '')
  if (!text) return null
  try {
    return JSON.parse(text)
  } catch {
    return text
  }
}

async function failure(res) {
  const body = await readBody(res)
  const code = body && typeof body === 'object' ? (body.error ?? body.detail?.error ?? null) : null
  const message = (typeof code === 'string' && code) || res.statusText || `HTTP ${res.status}`
  return new NotesApiError(message, { status: res.status, body, code: typeof code === 'string' ? code : null })
}

/** The X-Arp-Attachments header: JSON, or base64 of JSON. Anything else yields []. */
export function parseAttachmentsHeader(value) {
  if (!value) return []
  for (const attempt of [() => value, () => atob(value)]) {
    try {
      const parsed = JSON.parse(attempt())
      if (Array.isArray(parsed)) return parsed
    } catch {
      /* try the next encoding */
    }
  }
  return []
}

/**
 * @param {Object} options
 * @param {(url: string, init?: RequestInit) => Promise<Response>} options.fetch
 *   The host's authenticated fetch (Bearer, 401 refresh). Must resolve to a Response.
 * @param {(url: string, init?: RequestInit) => Promise<Response>} [options.fetchRaw]
 *   Plain fetch with no Authorization, for presigned upload URLs. Defaults to globalThis.fetch.
 * @param {string} [options.baseUrl]  Where the routes are mounted. Default '/api/v1'.
 * @param {boolean} [options.validate]  Check every response against the vendored schema. Default true.
 * @param {() => XMLHttpRequest} [options.createXhr]  XHR factory for progress reporting; tests inject one.
 */
export function createNotesApi({
  fetch: authedFetch,
  fetchRaw,
  baseUrl = '/api/v1',
  validate = true,
  createXhr = typeof XMLHttpRequest === 'undefined' ? null : () => new XMLHttpRequest(),
} = {}) {
  if (typeof authedFetch !== 'function') throw new TypeError('createNotesApi: options.fetch is required')
  const raw = fetchRaw ?? ((...args) => globalThis.fetch(...args))
  const root = String(baseUrl).replace(/\/+$/, '')
  const check = (name, value) => (validate ? assertShape(name, value) : value)
  const seg = (value) => encodeURIComponent(String(value))

  async function call(method, path, { query, body, model } = {}) {
    const init = { method, headers: { Accept: 'application/json' } }
    if (body !== undefined) {
      init.headers['Content-Type'] = 'application/json'
      init.body = JSON.stringify(body)
    }
    const res = await authedFetch(`${root}${path}${toQuery(query)}`, init)
    if (!res.ok) throw await failure(res)
    if (res.status === 204) return null
    const json = await res.json()
    return model ? check(model, json) : json
  }

  async function putUploadXhr(url, file, contentType, onProgress, signal) {
    return new Promise((resolve, reject) => {
      const xhr = createXhr()
      xhr.open('PUT', url)
      xhr.setRequestHeader('Content-Type', contentType)
      xhr.upload.onprogress = (event) => {
        const total = event.lengthComputable ? event.total : 0
        onProgress({ loaded: event.loaded, total, fraction: total ? event.loaded / total : 0 })
      }
      xhr.onerror = () => reject(new Error('Upload failed: network error'))
      xhr.onabort = () => reject(new DOMException('Upload aborted', 'AbortError'))
      xhr.onload = () => {
        let body = null
        try {
          body = xhr.responseText ? JSON.parse(xhr.responseText) : null
        } catch {
          body = xhr.responseText
        }
        if (xhr.status >= 200 && xhr.status < 300) {
          try {
            resolve(check('UploadResult', body))
          } catch (err) {
            reject(err)
          }
          return
        }
        const code = body && typeof body === 'object' && typeof body.error === 'string' ? body.error : null
        reject(new NotesApiError(code ?? `HTTP ${xhr.status}`, { status: xhr.status, body, code }))
      }
      if (signal) {
        if (signal.aborted) return reject(new DOMException('Upload aborted', 'AbortError'))
        signal.addEventListener('abort', () => xhr.abort(), { once: true })
      }
      xhr.send(file)
    })
  }

  return {
    /** GET /notes -> {items, next_cursor, sync_sources}. params: kind, origin, source_system, q, date_from, date_to, limit, before, include_deleted. */
    async listNotes(params = {}) {
      const list = await call('GET', '/notes', { query: params, model: 'NoteList' })
      return { next_cursor: null, sync_sources: [], ...list }
    },
    getNote: (id) => call('GET', `/notes/${seg(id)}`, { model: 'Note' }),
    createNote: (body) => call('POST', '/notes', { body, model: 'Note' }),
    patchNote: (id, body) => call('PATCH', `/notes/${seg(id)}`, { body, model: 'Note' }),
    /** PATCH /notes/{id}/autosave -> {note} | {conflict: true, server_version, server_data}. */
    autosaveNote: (id, body_md, version) =>
      call('PATCH', `/notes/${seg(id)}/autosave`, { body: { body_md, version }, model: 'AutosaveResult' }),
    async deleteNote(id) {
      await call('DELETE', `/notes/${seg(id)}`)
      return null
    },
    /** GET /notes/by-entity/{type}/{id}; opts: limit, include_children. */
    notesForEntity: (entityType, entityId, opts = {}) =>
      call('GET', `/notes/by-entity/${seg(entityType)}/${seg(entityId)}`, { query: opts, model: 'EntityNotes' }),
    /** POST /notes/{id}/propose. opts: llm (default false), refresh (default false). 503 llm_disabled -> NotesApiError.code. */
    proposeEnrichment: (id, { llm = false, refresh = false } = {}) =>
      call('POST', `/notes/${seg(id)}/propose`, { query: { llm, ...(refresh ? { refresh } : {}) }, model: 'Proposal' }),
    confirmEnrichment: (id, body) => call('POST', `/notes/${seg(id)}/confirm`, { body, model: 'ConfirmResult' }),
    requestUploadUrl: ({ sha256, mime, size_bytes, filename }) =>
      call('POST', '/attachments/upload-url', { body: { sha256, mime, size_bytes, filename }, model: 'UploadUrlResult' }),
    /**
     * PUT the raw bytes to a presigned upload_url with no Authorization header. With `onProgress`
     * (and XHR available) the upload goes through XHR so progress events exist; otherwise fetchRaw.
     * @param {string} uploadUrl
     * @param {Blob} file
     * @param {{mime?: string, onProgress?: (p: import('./types.js').UploadProgress) => void, signal?: AbortSignal}} [opts]
     */
    async putUpload(uploadUrl, file, { mime, onProgress, signal } = {}) {
      const contentType = mime || file.type || 'application/octet-stream'
      if (onProgress && createXhr) return putUploadXhr(uploadUrl, file, contentType, onProgress, signal)
      const res = await raw(uploadUrl, { method: 'PUT', headers: { 'Content-Type': contentType }, body: file, signal })
      if (!res.ok) throw await failure(res)
      return check('UploadResult', await res.json())
    },
    sha256OfFile,
    getCapabilities: () => call('GET', '/notes/capabilities', { model: 'Capabilities' }),
    /** GET /notes/{id}/export -> {markdown, manifest}. opts: withEnrichment, enrichmentStyle ('frontmatter'|'companion'). */
    async exportNote(id, { withEnrichment = false, enrichmentStyle } = {}) {
      const query = { with_enrichment: withEnrichment, ...(withEnrichment && enrichmentStyle ? { enrichment_style: enrichmentStyle } : {}) }
      const res = await authedFetch(`${root}/notes/${seg(id)}/export${toQuery(query)}`, { method: 'GET', headers: { Accept: 'text/markdown' } })
      if (!res.ok) throw await failure(res)
      return { markdown: await res.text(), manifest: parseAttachmentsHeader(res.headers?.get?.('X-Arp-Attachments')) }
    },
    /** POST /notes/{id}/resolve-tombstone, action 'keep' | 'delete' (K§6.3). */
    resolveTombstone: (id, action) =>
      call('POST', `/notes/${seg(id)}/resolve-tombstone`, { body: { action }, model: 'ResolveTombstoneResult' }),
  }
}
