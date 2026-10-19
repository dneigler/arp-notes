import { describe, expect, it, vi } from 'vitest'
import {
  NotesApiError,
  NotesSchemaError,
  createNotesApi,
  formatUploadProgress,
  parseAttachmentsHeader,
  sha256OfFile,
  toQuery,
} from '../src/api/index.js'
import { example } from './helpers.js'

function jsonResponse(body, init = {}) {
  return new Response(body === null ? null : JSON.stringify(body), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
    ...init,
  })
}

/** An authenticated-fetch double that answers from `responder(url, init)` and records calls. */
function harness(responder, options = {}) {
  const calls = []
  const fetch = vi.fn(async (url, init) => {
    calls.push({ url, init })
    return responder(url, init)
  })
  const fetchRaw = vi.fn(async (url, init) => jsonResponse(example('UploadResult'), { status: 201 }))
  const api = createNotesApi({ fetch, fetchRaw, baseUrl: '/api/v1', ...options })
  return { api, calls, fetch, fetchRaw }
}

describe('toQuery', () => {
  it('drops empty values and writes booleans as true/false', () => {
    expect(toQuery({ q: 'etude', kind: '', limit: 20, include_deleted: false, before: null, x: undefined })).toBe(
      '?q=etude&limit=20&include_deleted=false',
    )
    expect(toQuery({})).toBe('')
  })
})

describe('routes (A.2)', () => {
  it('listNotes -> GET /notes?… and returns {items, next_cursor, sync_sources}', async () => {
    const { api, calls } = harness(() => jsonResponse(example('NoteList')))
    const out = await api.listNotes({ origin: 'source', q: 'howat', include_deleted: true })
    expect(calls[0].url).toBe('/api/v1/notes?origin=source&q=howat&include_deleted=true')
    expect(calls[0].init.method).toBe('GET')
    expect(out).toHaveProperty('items')
    expect(out).toHaveProperty('next_cursor')
    expect(out).toHaveProperty('sync_sources')
    expect(out.items).toHaveLength(1)
    expect(out.next_cursor).toBeTruthy()
    expect(out.sync_sources[0]).toMatchObject({ source_system: 'obsidian', note_count: 14 })
  })

  it('listNotes fills next_cursor and sync_sources when the server leaves them out of a minimal answer', async () => {
    const { api } = harness(() => jsonResponse({ items: [], sync_sources: [] }))
    expect(await api.listNotes()).toEqual({ items: [], next_cursor: null, sync_sources: [] })
  })

  it('getNote / createNote / patchNote / deleteNote', async () => {
    const note = example('Note')
    const { api, calls } = harness((url, init) => (init.method === 'DELETE' ? new Response(null, { status: 204 }) : jsonResponse(note)))
    expect((await api.getNote(7)).id).toBe(7)
    await api.createNote({ title: 'T', body_md: 'x' })
    await api.patchNote(7, { kind: 'lecture' })
    expect(await api.deleteNote(7)).toBeNull()
    expect(calls.map((c) => `${c.init.method} ${c.url}`)).toEqual([
      'GET /api/v1/notes/7',
      'POST /api/v1/notes',
      'PATCH /api/v1/notes/7',
      'DELETE /api/v1/notes/7',
    ])
    expect(JSON.parse(calls[1].init.body)).toEqual({ title: 'T', body_md: 'x' })
    expect(calls[1].init.headers['Content-Type']).toBe('application/json')
  })

  it('autosaveNote sends {body_md, version} and returns the house envelope (note or conflict)', async () => {
    const { api, calls } = harness(() => jsonResponse(example('AutosaveResult')))
    const out = await api.autosaveNote(7, 'new body', 3)
    expect(calls[0].url).toBe('/api/v1/notes/7/autosave')
    expect(JSON.parse(calls[0].init.body)).toEqual({ body_md: 'new body', version: 3 })
    expect(out).toBeTruthy()
  })

  it('notesForEntity passes limit and include_children', async () => {
    const { api, calls } = harness(() => jsonResponse(example('EntityNotes')))
    await api.notesForEntity('repertoire', 35, { limit: 5, include_children: true })
    expect(calls[0].url).toBe('/api/v1/notes/by-entity/repertoire/35?limit=5&include_children=true')
  })

  it('proposeEnrichment sends llm and only sends refresh when asked', async () => {
    const { api, calls } = harness(() => jsonResponse(example('Proposal')))
    await api.proposeEnrichment(7)
    await api.proposeEnrichment(7, { llm: true, refresh: true })
    expect(calls[0].url).toBe('/api/v1/notes/7/propose?llm=false')
    expect(calls[1].url).toBe('/api/v1/notes/7/propose?llm=true&refresh=true')
    expect(calls[0].init.method).toBe('POST')
  })

  it('confirmEnrichment posts the ConfirmBody', async () => {
    const body = example('ConfirmBody')
    const { api, calls } = harness(() => jsonResponse(example('ConfirmResult')))
    const out = await api.confirmEnrichment(7, body)
    expect(JSON.parse(calls[0].init.body)).toEqual(body)
    expect(out).toHaveProperty('links_created')
  })

  it('getCapabilities and resolveTombstone', async () => {
    const { api, calls } = harness((url) =>
      jsonResponse(url.endsWith('/capabilities') ? example('Capabilities') : example('ResolveTombstoneResult')),
    )
    expect((await api.getCapabilities()).protocol).toBe(1)
    await api.resolveTombstone(7, 'keep')
    expect(calls[1].url).toBe('/api/v1/notes/7/resolve-tombstone')
    expect(JSON.parse(calls[1].init.body)).toEqual({ action: 'keep' })
  })

  it('requestUploadUrl posts the four ticket fields', async () => {
    const { api, calls } = harness(() => jsonResponse(example('UploadUrlResult')))
    const out = await api.requestUploadUrl({ sha256: 'a'.repeat(64), mime: 'image/png', size_bytes: 9, filename: 'a.png' })
    expect(calls[0].url).toBe('/api/v1/attachments/upload-url')
    expect(JSON.parse(calls[0].init.body)).toEqual({ sha256: 'a'.repeat(64), mime: 'image/png', size_bytes: 9, filename: 'a.png' })
    expect(out.status).toBe('upload')
  })

  it('honours a custom baseUrl', async () => {
    const { api, calls } = harness(() => jsonResponse(example('Capabilities')), { baseUrl: 'https://host.test/notes-api/' })
    await api.getCapabilities()
    expect(calls[0].url).toBe('https://host.test/notes-api/notes/capabilities')
  })

  it('requires a fetch', () => {
    expect(() => createNotesApi({})).toThrow(/fetch is required/)
  })
})

describe('exportNote', () => {
  it('returns {markdown, manifest} from the body and the X-Arp-Attachments header', async () => {
    const manifest = [{ filename: 'a.png', sha256: 'a'.repeat(64), path: 'a.png' }]
    const { api, calls } = harness(
      () => new Response('# Hello\n', { status: 200, headers: { 'Content-Type': 'text/markdown', 'X-Arp-Attachments': JSON.stringify(manifest) } }),
    )
    const out = await api.exportNote(7, { withEnrichment: true, enrichmentStyle: 'companion' })
    expect(calls[0].url).toBe('/api/v1/notes/7/export?with_enrichment=true&enrichment_style=companion')
    expect(out).toEqual({ markdown: '# Hello\n', manifest })
  })

  it('defaults to no enrichment and an empty manifest when the header is absent', async () => {
    const { api, calls } = harness(() => new Response('x', { status: 200 }))
    expect(await api.exportNote(7)).toEqual({ markdown: 'x', manifest: [] })
    expect(calls[0].url).toBe('/api/v1/notes/7/export?with_enrichment=false')
  })

  it('maps 403 (export off) to a NotesApiError', async () => {
    const { api } = harness(() => jsonResponse({ error: 'export_disabled' }, { status: 403 }))
    await expect(api.exportNote(7)).rejects.toMatchObject({ name: 'NotesApiError', status: 403, code: 'export_disabled' })
  })

  it('parseAttachmentsHeader reads JSON or base64 JSON and ignores junk', () => {
    const list = [{ filename: 'é.png' }]
    expect(parseAttachmentsHeader(JSON.stringify(list))).toEqual(list)
    expect(parseAttachmentsHeader(btoa(JSON.stringify([{ a: 1 }])))).toEqual([{ a: 1 }])
    expect(parseAttachmentsHeader('not json')).toEqual([])
    expect(parseAttachmentsHeader(null)).toEqual([])
  })
})

describe('errors', () => {
  it('turns a non-2xx answer into NotesApiError with status, body and the error code', async () => {
    const { api } = harness(() => jsonResponse({ error: 'read_only_import' }, { status: 409 }))
    const err = await api.patchNote(7, { title: 'x' }).catch((e) => e)
    expect(err).toBeInstanceOf(NotesApiError)
    expect(err).toMatchObject({ status: 409, code: 'read_only_import', body: { error: 'read_only_import' } })
  })

  it('llm_disabled (503) is reachable through code', async () => {
    const { api } = harness(() => jsonResponse({ error: 'llm_disabled' }, { status: 503 }))
    await expect(api.proposeEnrichment(7, { llm: true })).rejects.toMatchObject({ code: 'llm_disabled', status: 503 })
  })

  it('a non-JSON error body still yields a NotesApiError', async () => {
    const { api } = harness(() => new Response('bad gateway', { status: 502, statusText: 'Bad Gateway' }))
    await expect(api.getNote(1)).rejects.toMatchObject({ status: 502, code: null, message: 'Bad Gateway' })
  })
})

describe('ajv validation against the vendored core schemas', () => {
  it('rejects a response with a bad shape', async () => {
    const bad = { ...example('Note'), id: 'seven', links: 'none' }
    const { api } = harness(() => jsonResponse(bad))
    const err = await api.getNote(7).catch((e) => e)
    expect(err).toBeInstanceOf(NotesSchemaError)
    expect(err.schemaName).toBe('Note')
    expect(err.errors.length).toBeGreaterThan(0)
  })

  it('rejects a missing required field', async () => {
    const { id: _id, ...noId } = example('Note')
    const { api } = harness(() => jsonResponse(noId))
    await expect(api.getNote(7)).rejects.toBeInstanceOf(NotesSchemaError)
  })

  it('tolerates unknown fields (clients must)', async () => {
    const { api } = harness(() => jsonResponse({ ...example('Note'), brand_new_field: { x: 1 } }))
    expect((await api.getNote(7)).id).toBe(7)
  })

  it('can be turned off', async () => {
    const { api } = harness(() => jsonResponse({ nonsense: true }), { validate: false })
    expect(await api.getNote(7)).toEqual({ nonsense: true })
  })
})

describe('uploads (A.4)', () => {
  const file = new Blob([new Uint8Array([1, 2, 3, 4])], { type: 'image/png' })

  it('putUpload goes through fetchRaw with the mime and no Authorization', async () => {
    const { api, fetch, fetchRaw } = harness(() => jsonResponse({}))
    const out = await api.putUpload('https://notes.example.test/api/v1/attachments/upload/abc', file)
    expect(fetch).not.toHaveBeenCalled()
    const [url, init] = fetchRaw.mock.calls[0]
    expect(url).toBe('https://notes.example.test/api/v1/attachments/upload/abc')
    expect(init.method).toBe('PUT')
    expect(init.body).toBe(file)
    expect(init.headers).toEqual({ 'Content-Type': 'image/png' })
    expect(Object.keys(init.headers).map((k) => k.toLowerCase())).not.toContain('authorization')
    expect(out.blob_id).toBe(1)
  })

  it('an explicit mime overrides the blob type; failures carry the server code', async () => {
    const { api, fetchRaw } = harness(() => jsonResponse({}))
    fetchRaw.mockResolvedValueOnce(jsonResponse({ error: 'hash_mismatch' }, { status: 409 }))
    await expect(api.putUpload('/u/1', file, { mime: 'application/pdf' })).rejects.toMatchObject({ status: 409, code: 'hash_mismatch' })
    expect(fetchRaw.mock.calls[0][1].headers['Content-Type']).toBe('application/pdf')
  })

  class FakeXhr {
    constructor() {
      this.upload = {}
      this.headers = {}
      FakeXhr.last = this
    }
    open(method, url) {
      this.method = method
      this.url = url
    }
    setRequestHeader(k, v) {
      this.headers[k] = v
    }
    send(body) {
      this.body = body
    }
    abort() {
      this.onabort?.()
    }
  }

  it('reports progress through XHR (feeds "62% · 1.8 of 2.9 MB") and sends no Authorization', async () => {
    const { api, fetchRaw } = harness(() => jsonResponse({}), { createXhr: () => new FakeXhr() })
    const seen = []
    const promise = api.putUpload('https://u.test/x', file, { onProgress: (p) => seen.push(p) })
    const xhr = FakeXhr.last
    expect(xhr.method).toBe('PUT')
    expect(xhr.headers).toEqual({ 'Content-Type': 'image/png' })
    expect(xhr.body).toBe(file)
    xhr.upload.onprogress({ lengthComputable: true, loaded: 1.8 * 1024 * 1024, total: 2.9 * 1024 * 1024 })
    xhr.status = 201
    xhr.responseText = JSON.stringify(example('UploadResult'))
    xhr.onload()
    expect((await promise).blob_id).toBe(1)
    expect(fetchRaw).not.toHaveBeenCalled()
    expect(seen).toHaveLength(1)
    expect(seen[0].fraction).toBeCloseTo(0.62, 2)
    expect(formatUploadProgress(seen[0])).toBe('62% · 1.8 of 2.9 MB')
  })

  it('XHR failures reject with the server code; abort rejects with AbortError', async () => {
    const { api } = harness(() => jsonResponse({}), { createXhr: () => new FakeXhr() })
    const failed = api.putUpload('https://u.test/x', file, { onProgress() {} })
    Object.assign(FakeXhr.last, { status: 413, responseText: '{"error":"too_large"}' })
    FakeXhr.last.onload()
    await expect(failed).rejects.toMatchObject({ status: 413, code: 'too_large' })

    const controller = new AbortController()
    const aborted = api.putUpload('https://u.test/x', file, { onProgress() {}, signal: controller.signal })
    controller.abort()
    await expect(aborted).rejects.toMatchObject({ name: 'AbortError' })
  })

  it('falls back to fetchRaw when onProgress is given but XHR is unavailable', async () => {
    const { api, fetchRaw } = harness(() => jsonResponse({}), { createXhr: null })
    await api.putUpload('https://u.test/x', file, { onProgress() {} })
    expect(fetchRaw).toHaveBeenCalledOnce()
  })
})

describe('sha256OfFile', () => {
  it('matches the NIST vector for "abc"', async () => {
    expect(await sha256OfFile(new Blob(['abc']))).toBe('ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad')
  })

  it('is lower-case 64 hex and exposed on the api object', async () => {
    const { api } = harness(() => jsonResponse({}))
    expect(await api.sha256OfFile(new Blob([]))).toBe('e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855')
  })
})

describe('formatUploadProgress', () => {
  it('formats MB with one decimal and caps at 100%', () => {
    expect(formatUploadProgress({ loaded: 0, total: 3 * 1024 * 1024 })).toBe('0% · 0.0 of 3.0 MB')
    expect(formatUploadProgress({ loaded: 5 * 1024 * 1024, total: 4 * 1024 * 1024 })).toBe('100% · 5.0 of 4.0 MB')
  })

  it('reads small files in KB and copes with an unknown total', () => {
    expect(formatUploadProgress({ loaded: 512 * 1024 / 2, total: 512 * 1024 })).toBe('50% · 256 of 512 KB')
    expect(formatUploadProgress({ loaded: 2 * 1024 * 1024, total: 0 })).toBe('2.0 MB')
  })
})
