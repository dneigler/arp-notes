// @vitest-environment jsdom
// livePreview() in a mounted NoteEditor: heading lines, dimmed markers, cursor-line reveal, the Source toggle
// keeping the selection, and inline images through resolveAttachment.
import { EditorSelection } from '@codemirror/state'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { bodyOf } from '../src/editor/index.js'
import { livePreview, previewModeOf, refreshPreview, setPreviewMode, switchPreviewMode } from '../src/preview/index.js'
import { act, cleanup } from './helpers.js'
import { mountEditor, settle } from './editor-helpers.js'

afterEach(cleanup)

const BODY = '# Masterclass\n\nPlayed **slowly** today\n\n- first\n- second\n'
const lines = (container, cls) => [...container.querySelectorAll(`.cm-line.${cls}`)].map((l) => l.textContent)
const dimmed = (container) => [...container.querySelectorAll('.arpn-lp-mark')].map((n) => n.textContent)
const moveTo = (view, anchor, head = anchor) => act(() => view.dispatch({ selection: EditorSelection.single(anchor, head) }))

describe('live preview', () => {
  it('sizes heading lines by level and dims the markers away from the cursor', async () => {
    const { container, view } = mountEditor({ value: '# One\n\n## Two\n\nbody **x**\n', extensions: [livePreview()] })
    await settle()
    moveTo(view, view.state.doc.length)
    expect(lines(container, 'arpn-lp-h1')).toEqual(['# One'])
    expect(lines(container, 'arpn-lp-h2')).toEqual(['## Two'])
    expect(dimmed(container)).toEqual(expect.arrayContaining(['#', '##']))
  })

  it('reveals the cursor line: its markers are not dimmed, and the line carries the band', async () => {
    const { container, view } = mountEditor({ value: BODY, extensions: [livePreview()] })
    await settle()
    moveTo(view, BODY.indexOf('slowly'))
    expect(lines(container, 'arpn-lp-active')).toEqual(['Played **slowly** today'])
    const dimmedText = dimmed(container)
    // '#' and the list dashes still dim; the ** pair on the cursor line does not.
    expect(dimmedText).toEqual(expect.arrayContaining(['#', '-']))
    expect(dimmedText).not.toContain('**')
    moveTo(view, 0)
    expect(lines(container, 'arpn-lp-active')).toEqual(['# Masterclass'])
    expect(dimmedText.length).toBeGreaterThan(0)
    expect(dimmed(container)).toContain('**')
  })

  it('Source mode has no preview decorations, keeps the selection, and brings the preview back', async () => {
    const { container, view } = mountEditor({ value: BODY, extensions: [livePreview()] })
    await settle()
    const at = BODY.indexOf('second')
    moveTo(view, at, at + 3)
    expect(previewModeOf(view.state)).toBe('preview')
    expect(lines(container, 'arpn-lp-h1')).toHaveLength(1)

    act(() => switchPreviewMode(view, 'source'))
    expect(previewModeOf(view.state)).toBe('source')
    expect(container.querySelectorAll('[class*="arpn-lp-"]')).toHaveLength(0)
    expect(view.state.selection.main).toMatchObject({ from: at, to: at + 3 })
    expect(bodyOf(view.state)).toBe(BODY)
    // The C6d source styling is still there.
    expect(container.querySelector('.arpn-md-mark')).not.toBeNull()

    act(() => view.dispatch({ effects: setPreviewMode.of('preview') }))
    expect(lines(container, 'arpn-lp-h1')).toHaveLength(1)
    expect(view.state.selection.main).toMatchObject({ from: at, to: at + 3 })
  })

  it('starts in Source mode when asked', async () => {
    const { container, view } = mountEditor({ value: BODY, extensions: [livePreview({ mode: 'source' })] })
    await settle()
    expect(previewModeOf(view.state)).toBe('source')
    expect(container.querySelectorAll('[class*="arpn-lp-"]')).toHaveLength(0)
  })

  it('previewModeOf reads "source" for an editor without the layer', async () => {
    const { view } = mountEditor({ value: BODY })
    expect(previewModeOf(view.state)).toBe('source')
  })

  it('follows edits: a heading typed in gets its size, one deleted loses it', async () => {
    const { container, view } = mountEditor({ value: 'plain', extensions: [livePreview()] })
    await settle()
    expect(lines(container, 'arpn-lp-h2')).toEqual([])
    act(() => view.dispatch({ changes: { from: 0, insert: '## ' }, userEvent: 'input.type' }))
    expect(lines(container, 'arpn-lp-h2')).toEqual(['## plain'])
    act(() => view.dispatch({ changes: { from: 0, to: 3 }, userEvent: 'delete.backward' }))
    expect(lines(container, 'arpn-lp-h2')).toEqual([])
  })
})

describe('inline images', () => {
  const DOC = 'Before\n\n![IMG_2040.png](attachment://41)\n\n![[Howat.png|438x282]]\n\nAfter\n'
  const images = (container) => [...container.querySelectorAll('.arpn-lp-image')]

  it('draws attachment images and Obsidian embeds through resolveAttachment and leaves the Markdown alone', async () => {
    const resolveAttachment = vi.fn(async (ref) => `https://files.test/${ref.kind}/${encodeURIComponent(ref.target)}`)
    const { container, view } = mountEditor({ value: DOC, extensions: [livePreview({ resolveAttachment })] })
    moveTo(view, 0)
    expect(images(container)).toHaveLength(2)
    expect(images(container)[0].dataset.state).toBe('pending')
    await settle()
    const imgs = [...container.querySelectorAll('.arpn-lp-image img')]
    expect(imgs.map((i) => i.getAttribute('src'))).toEqual([
      'https://files.test/attachment/attachment%3A%2F%2F41',
      'https://files.test/embed/Howat.png',
    ])
    expect(imgs[0].alt).toBe('IMG_2040.png')
    expect(imgs[1].getAttribute('width')).toBe('438')
    expect(imgs[1].getAttribute('height')).toBe('282')
    expect(resolveAttachment).toHaveBeenCalledWith(expect.objectContaining({ kind: 'attachment', id: '41', text: '![IMG_2040.png](attachment://41)' }))
    expect(resolveAttachment).toHaveBeenCalledWith(expect.objectContaining({ kind: 'embed', text: '![[Howat.png|438x282]]' }))
    expect(bodyOf(view.state)).toBe(DOC)
  })

  it('asks the host once per image, however many times the view redraws', async () => {
    const resolveAttachment = vi.fn(async () => 'https://files.test/a.png')
    const { view } = mountEditor({ value: DOC, extensions: [livePreview({ resolveAttachment })] })
    await settle()
    moveTo(view, 3)
    moveTo(view, DOC.length)
    act(() => view.dispatch({ changes: { from: DOC.length, insert: 'x' } }))
    expect(resolveAttachment).toHaveBeenCalledTimes(2)
  })

  it('shows the Markdown while the cursor is inside an image', async () => {
    const { container, view } = mountEditor({ value: DOC, extensions: [livePreview({ resolveAttachment: async () => 'https://files.test/a.png' })] })
    await settle()
    moveTo(view, DOC.indexOf('IMG_2040') + 2)
    await settle()
    expect(images(container)).toHaveLength(1)
    expect(container.textContent).toContain('![IMG_2040.png](attachment://41)')
  })

  it('a click on an image puts the cursor inside it', async () => {
    const { container, view } = mountEditor({ value: DOC, extensions: [livePreview({ resolveAttachment: async () => 'https://files.test/a.png' })] })
    await settle()
    const first = images(container)[0]
    first.dispatchEvent(new MouseEvent('mousedown', { bubbles: true, cancelable: true }))
    const head = view.state.selection.main.head
    expect(head).toBeGreaterThan(DOC.indexOf('![IMG_2040'))
    expect(head).toBeLessThan(DOC.indexOf('![IMG_2040') + '![IMG_2040.png](attachment://41)'.length)
  })

  it('says "image not found" when the host has no URL, and when it throws', async () => {
    const { container } = mountEditor({
      value: DOC,
      extensions: [livePreview({ resolveAttachment: (ref) => (ref.kind === 'embed' ? null : Promise.reject(new Error('boom'))) })],
    })
    await settle()
    const missing = images(container)
    expect(missing.map((m) => m.dataset.state)).toEqual(['missing', 'missing'])
    expect(missing[0].textContent).toBe('IMG_2040.png · image not found')
    expect(missing[1].textContent).toBe('Howat.png · image not found')
  })

  it('an image that fails to load (an expired signed URL) reports it and reads "image not found"', async () => {
    const onAttachmentExpired = vi.fn()
    const { container } = mountEditor({
      value: '![a.png](attachment://7)',
      extensions: [livePreview({ resolveAttachment: async () => 'https://files.test/old.png', onAttachmentExpired })],
    })
    await settle()
    const img = container.querySelector('.arpn-lp-image img')
    act(() => {
      img.dispatchEvent(new Event('error'))
    })
    expect(onAttachmentExpired).toHaveBeenCalledWith(expect.objectContaining({ id: '7' }))
    expect(container.querySelector('.arpn-lp-image').dataset.state).toBe('missing')
  })

  it('refreshPreview asks the host again, so a renewed URL replaces the dead one', async () => {
    let url = 'https://files.test/old.png'
    const resolveAttachment = vi.fn(async () => url)
    const { container, view } = mountEditor({ value: '![a.png](attachment://7)\n\ntext', extensions: [livePreview({ resolveAttachment })] })
    moveTo(view, view.state.doc.length)
    await settle()
    expect(container.querySelector('.arpn-lp-image img').getAttribute('src')).toBe(url)
    url = 'https://files.test/new.png'
    act(() => view.dispatch({ effects: refreshPreview.of(null) }))
    await settle()
    expect(container.querySelector('.arpn-lp-image img').getAttribute('src')).toBe(url)
    expect(resolveAttachment).toHaveBeenCalledTimes(2)
  })

  it('leaves images as Markdown without resolveAttachment, and in Source mode', async () => {
    const plain = mountEditor({ value: DOC, extensions: [livePreview()] })
    await settle()
    expect(images(plain.container)).toHaveLength(0)
    expect(plain.container.textContent).toContain('![IMG_2040.png](attachment://41)')

    const sourced = mountEditor({ value: DOC, extensions: [livePreview({ mode: 'source', resolveAttachment: async () => 'https://files.test/a.png' })] })
    await settle()
    expect(images(sourced.container)).toHaveLength(0)
  })

  it('does not touch the upload placeholder an in-flight paste leaves in the document', async () => {
    const doc = '![uploading x.png…](attachment://pending-abc)\n'
    const { container } = mountEditor({ value: doc, extensions: [livePreview({ resolveAttachment: async () => 'https://files.test/a.png' })] })
    await settle()
    expect(images(container)).toHaveLength(0)
    expect(container.textContent).toContain('attachment://pending-abc')
  })

  it('keeps the host link chips of C6d working beside images', async () => {
    const scheme = { prefix: 'ex', search: async () => [], resolve: async () => ({ title: 'Études' }) }
    const { container } = mountEditor({
      value: 'See [@Études](ex://repertoire/35)\n\n![a.png](attachment://7)\n',
      schemes: [scheme],
      extensions: [livePreview({ resolveAttachment: async () => 'https://files.test/a.png' })],
    })
    await settle()
    expect(container.querySelectorAll('.arpn-chip')).toHaveLength(1)
    expect(container.querySelectorAll('.arpn-lp-image img')).toHaveLength(1)
  })
})
