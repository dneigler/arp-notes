// @vitest-environment jsdom
// Paste/drop upload and the attachment policy (ADR D4, K§8, K§12 capabilities).
import { afterEach, describe, expect, it, vi } from 'vitest'
import { allowedLabel, checkFile, formatSize, policyFooter } from '../src/editor/policy.js'
import { stripPlaceholders } from '../src/editor/scan.js'
import { EDITOR_STRINGS } from '../src/editor/strings.js'
import { act, cleanup } from './helpers.js'
import { deferred, dropFiles, file, mountEditor, pasteFiles, settle } from './editor-helpers.js'

afterEach(cleanup)

const MIB = 1024 * 1024
const CAPS = {
  protocol: 1,
  attachments: true,
  mime_allowlist: ['image/webp', 'image/png', 'application/pdf'],
  limits: { max_attachment_bytes: 25 * MIB },
  export: true,
}

const dialog = () => document.querySelector('[role=dialog]')
const status = (container) => container.querySelector('[data-arpn=note-editor] > [role=status]')

describe('paste', () => {
  it('inserts a placeholder at once, shows progress, then swaps it for the blob reference', async () => {
    const gate = deferred()
    let report
    const upload = vi.fn((f, { onProgress }) => {
      report = onProgress
      return gate.promise
    })
    const seen = []
    const { container, view } = mountEditor({ value: 'Intro\n', capabilities: CAPS, upload, onChange: (b) => seen.push(b) })
    act(() => view.dispatch({ selection: { anchor: 6 } }))

    const event = pasteFiles(view.contentDOM, [file('IMG_2041.png', 'image/png', 2.9 * MIB)])
    expect(event.defaultPrevented).toBe(true)
    expect(upload).toHaveBeenCalledTimes(1)
    const body = view.state.doc.toString()
    expect(body).toMatch(/^Intro\n!\[uploading IMG_2041\.png…\]\(attachment:\/\/pending-[a-z0-9]+\)$/)

    act(() => report({ loaded: 1.8 * MIB, total: 2.9 * MIB }))
    const text = container.textContent
    expect(text).toContain('Uploading IMG_2041.png…')
    expect(text).toContain('62% · 1.8 of 2.9 MB')
    expect(text).toContain('Keep typing — the image appears when it lands')
    expect(container.querySelector('[role=progressbar]').getAttribute('aria-valuenow')).toBe('62')

    // Typing while the bytes travel is fine.
    act(() => view.dispatch({ changes: { from: 0, insert: '# ' } }))
    await act(async () => gate.resolve({ blob_id: 77, filename: 'IMG_2041.png' }))
    await settle()
    expect(view.state.doc.toString()).toBe('# Intro\n![IMG_2041.png](attachment://77)')
    expect(seen.at(-1)).toBe('# Intro\n![IMG_2041.png](attachment://77)')
    expect(container.textContent).not.toContain('Uploading')
  })

  it('uses the filename the host returns and the link form for a PDF', async () => {
    const upload = vi.fn(async () => ({ blob_id: 9, filename: 'score [final].pdf' }))
    const { view } = mountEditor({ value: '', capabilities: CAPS, upload })
    pasteFiles(view.contentDOM, [file('score.pdf', 'application/pdf', 1000)])
    await settle()
    expect(view.state.doc.toString()).toBe('[score final .pdf](attachment://9)')
  })

  it('puts several files on their own lines', async () => {
    const upload = vi.fn(async (f) => ({ blob_id: f.name === 'a.png' ? 1 : 2, filename: f.name }))
    const { view } = mountEditor({ value: '', capabilities: CAPS, upload })
    pasteFiles(view.contentDOM, [file('a.png'), file('b.png')])
    await settle()
    expect(view.state.doc.toString()).toBe('![a.png](attachment://1)\n![b.png](attachment://2)')
  })

  it('leaves a paste that carries text to the browser (a Finder or Word copy)', () => {
    const upload = vi.fn()
    const { view } = mountEditor({ value: '', capabilities: CAPS, upload })
    pasteFiles(view.contentDOM, [file('a.png')], 'a.png')
    expect(upload).not.toHaveBeenCalled()
    expect(dialog()).toBeNull()
    expect(view.state.doc.toString()).toBe('a.png') // CodeMirror's own text paste
  })

  it('ignores a paste without files', () => {
    const { view } = mountEditor({ value: '', capabilities: CAPS, upload: vi.fn() })
    pasteFiles(view.contentDOM, [], 'hello')
    expect(dialog()).toBeNull()
    expect(view.state.doc.toString()).toBe('hello')
  })

  it('drops the placeholder and says so when the upload fails', async () => {
    const upload = vi.fn(async () => {
      throw new Error('storage full')
    })
    const statuses = []
    const { container, view } = mountEditor({ value: 'keep', capabilities: CAPS, upload, onStatus: (s) => statuses.push(s) })
    act(() => view.dispatch({ selection: { anchor: 4 } }))
    pasteFiles(view.contentDOM, [file('big.png')])
    await settle()
    expect(view.state.doc.toString()).toBe('keep')
    expect(container.textContent).toContain('Couldn’t upload big.png — storage full')
    expect(statuses.at(-1).uploads[0].state).toBe('error')
    act(() => [...container.querySelectorAll('button')].find((b) => b.textContent === 'Dismiss').click())
    expect(container.textContent).not.toContain('Couldn’t upload')
  })

  it('does nothing when the placeholder was deleted before the upload landed', async () => {
    const gate = deferred()
    const { view } = mountEditor({ value: '', capabilities: CAPS, upload: () => gate.promise })
    pasteFiles(view.contentDOM, [file('a.png')])
    act(() => view.dispatch({ changes: { from: 0, to: view.state.doc.length } }))
    await act(async () => gate.resolve({ blob_id: 5, filename: 'a.png' }))
    await settle()
    expect(view.state.doc.toString()).toBe('')
  })

  it('accepts a bare number as progress', async () => {
    let report
    const { container, view } = mountEditor({ value: '', capabilities: CAPS, upload: (f, o) => ((report = o.onProgress), new Promise(() => {})) })
    pasteFiles(view.contentDOM, [file('a.png', 'image/png', 1000 * 1000)])
    act(() => report(0.5))
    expect(container.textContent).toContain('50%')
  })
})

describe('drop', () => {
  it('puts the placeholder where the file was dropped (posAtCoords)', async () => {
    const upload = vi.fn(async () => ({ blob_id: 3, filename: 'd.png' }))
    const { view } = mountEditor({ value: 'one two', capabilities: CAPS, upload })
    vi.spyOn(view, 'posAtCoords').mockReturnValue(3)
    const event = dropFiles(view.contentDOM, [file('d.png')], { x: 40, y: 8 })
    expect(event.defaultPrevented).toBe(true)
    expect(view.posAtCoords).toHaveBeenCalledWith({ x: 40, y: 8 })
    await settle()
    expect(view.state.doc.toString()).toBe('one![d.png](attachment://3) two')
  })

  it('falls back to the cursor when the drop point is off the text', async () => {
    const upload = vi.fn(async () => ({ blob_id: 3, filename: 'd.png' }))
    const { view } = mountEditor({ value: 'abc', capabilities: CAPS, upload })
    act(() => view.dispatch({ selection: { anchor: 3 } }))
    vi.spyOn(view, 'posAtCoords').mockReturnValue(null)
    dropFiles(view.contentDOM, [file('d.png')])
    await settle()
    expect(view.state.doc.toString()).toBe('abc![d.png](attachment://3)')
  })

  it('leaves a drop without files (text dragged inside the editor) to CodeMirror', () => {
    const { view } = mountEditor({ value: 'abc', capabilities: CAPS, upload: vi.fn() })
    expect(dropFiles(view.contentDOM, []).defaultPrevented).toBe(false)
  })
})

describe('policy', () => {
  it('attachments off: no upload, no placeholder, the dialog explains, text unchanged', async () => {
    const upload = vi.fn()
    const { view } = mountEditor({ value: 'my text', capabilities: { ...CAPS, attachments: false }, upload })
    const event = pasteFiles(view.contentDOM, [file('IMG_2041.png')])
    expect(event.defaultPrevented).toBe(true)
    expect(upload).not.toHaveBeenCalled()
    expect(view.state.doc.toString()).toBe('my text')
    const d = dialog()
    expect(d.getAttribute('aria-modal')).toBe('true')
    expect(d.querySelector('h2').textContent).toBe('Image not added')
    expect(d.textContent).toContain('This app doesn’t accept attachments, so the pasted image was left out. Your text is unchanged.')
    act(() => d.querySelector('button').click())
    expect(dialog()).toBeNull()
  })

  it('Esc closes the dialog too', () => {
    const { view } = mountEditor({ value: '', capabilities: { ...CAPS, attachments: false }, upload: vi.fn() })
    pasteFiles(view.contentDOM, [file('a.png')])
    expect(dialog()).not.toBeNull()
    act(() => {
      document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))
    })
    expect(dialog()).toBeNull()
  })

  it('treats missing capabilities or a missing upload function as attachments off', () => {
    const a = mountEditor({ value: '', upload: vi.fn() })
    pasteFiles(a.view.contentDOM, [file('a.png')])
    expect(dialog()).not.toBeNull()
    cleanup()
    const b = mountEditor({ value: '', capabilities: CAPS })
    pasteFiles(b.view.contentDOM, [file('a.png')])
    expect(dialog()).not.toBeNull()
  })

  it('refuses a type outside the allowlist, before any upload', () => {
    const upload = vi.fn()
    const { view } = mountEditor({ value: '', capabilities: CAPS, upload })
    pasteFiles(view.contentDOM, [file('clip.mov', 'video/quicktime', 1000)])
    expect(upload).not.toHaveBeenCalled()
    expect(view.state.doc.toString()).toBe('')
    expect(dialog().querySelector('h2').textContent).toBe('File not added')
    expect(dialog().textContent).toContain('clip.mov isn’t a type this app accepts (it allows Images and PDFs)')
  })

  it('refuses a file over the size limit, before any upload', () => {
    const upload = vi.fn()
    const { view } = mountEditor({ value: '', capabilities: CAPS, upload })
    pasteFiles(view.contentDOM, [file('huge.png', 'image/png', 31.4 * MIB)])
    expect(upload).not.toHaveBeenCalled()
    expect(dialog().querySelector('h2').textContent).toBe('Image not added')
    expect(dialog().textContent).toContain('huge.png is 31.4 MB, and this app accepts up to 25 MB')
  })

  it('uploads the acceptable files of a mixed paste and reports the one it left out', async () => {
    const upload = vi.fn(async (f) => ({ blob_id: 1, filename: f.name }))
    const { view } = mountEditor({ value: '', capabilities: CAPS, upload })
    pasteFiles(view.contentDOM, [file('ok.png'), file('no.mov', 'video/quicktime')])
    await settle()
    expect(upload).toHaveBeenCalledTimes(1)
    expect(view.state.doc.toString()).toBe('![ok.png](attachment://1)')
    expect(dialog().textContent).toContain('no.mov')
  })

  it('a null allowlist accepts any type', () => {
    expect(checkFile(file('x.zip', 'application/zip', 10), { ...CAPS, mime_allowlist: null })).toBeNull()
    expect(checkFile(file('x.png', 'image/png', 10), { ...CAPS, mime_allowlist: ['image/*'] })).toBeNull()
    expect(checkFile(file('x.mp3', 'audio/mpeg', 10), { ...CAPS, mime_allowlist: ['image/*'] })).toEqual({ reason: 'type' })
  })
})

describe('policy wording (rendered from capabilities)', () => {
  it('formats sizes', () => {
    expect(formatSize(25 * MIB)).toBe('25 MB')
    expect(formatSize(1.8 * MIB)).toBe('1.8 MB')
    expect(formatSize(2048)).toBe('2 KB')
    expect(formatSize(10)).toBe('1 KB')
  })

  it('names the allowed types', () => {
    expect(allowedLabel(['image/webp', 'image/png', 'application/pdf'], EDITOR_STRINGS)).toBe('Images and PDFs')
    expect(allowedLabel(['application/pdf'], EDITOR_STRINGS)).toBe('PDFs')
    expect(allowedLabel(['image/png', 'application/pdf', 'text/plain'], EDITOR_STRINGS)).toBe('Images, PDFs and text/plain')
    expect(allowedLabel(null, EDITOR_STRINGS)).toBe('Files')
  })

  it('writes the footer from the response', () => {
    expect(policyFooter(CAPS, EDITOR_STRINGS)).toBe('This app allows Images and PDFs up to 25 MB · export to Markdown on')
    expect(policyFooter({ ...CAPS, export: false, mime_allowlist: ['application/pdf'], limits: { max_attachment_bytes: 5 * MIB } }, EDITOR_STRINGS)).toBe(
      'This app allows PDFs up to 5 MB · export to Markdown off',
    )
    expect(policyFooter({ ...CAPS, attachments: false }, EDITOR_STRINGS)).toBe('This app doesn’t accept attachments · export to Markdown on')
    expect(policyFooter(undefined, EDITOR_STRINGS)).toBe('')
  })
})

describe('placeholders', () => {
  it('stripPlaceholders removes in-flight uploads only', () => {
    const body = 'a ![uploading x.png…](attachment://pending-abc123) b ![x](attachment://5) [uploading y.pdf…](attachment://pending-q1)'
    expect(stripPlaceholders(body)).toBe('a  b ![x](attachment://5) ')
    expect(stripPlaceholders('nothing here')).toBe('nothing here')
  })
})
