// @vitest-environment jsdom
// CI GATE (C6e, ADR D4): the preview layer only decorates. The spike's 33-construct corpus and the other
// fixtures give back an identical document string with the layer on, with it off, and across the switch,
// and survive an inserted and a deleted character byte for byte with the layer on.
import { EditorState } from '@codemirror/state'
import { WidgetType } from '@codemirror/view'
import { afterEach, describe, expect, it } from 'vitest'
import { bodyOf, markdownLanguage } from '../src/editor/index.js'
import { previewDecorations } from '../src/preview/decorations.js'
import { livePreview, previewModeOf, switchPreviewMode } from '../src/preview/index.js'
import { act, cleanup, fixtureText } from './helpers.js'
import { mountEditor, settle } from './editor-helpers.js'

afterEach(cleanup)

const FIXTURES = {
  'the spike 33-construct corpus': fixtureText('obsidian-synthetic.md'),
  'the masterclass-shaped note': fixtureText('masterclass-shaped.md'),
  'a CRLF note': fixtureText('obsidian-synthetic.md').replace(/\n/g, '\r\n'),
  'a note with a trailing newline': `${fixtureText('masterclass-shaped.md')}\n`,
  'the empty note': '',
}

const resolveAttachment = async (ref) => `https://files.test/${encodeURIComponent(ref.target)}`
const schemes = [{ prefix: 'ex', search: () => [], resolve: (type, id) => (id === 35 ? { title: 'Études' } : null) }]

describe.each(Object.entries(FIXTURES))('%s', (_name, body) => {
  it('is the same string with the preview on, off, and across the switch', async () => {
    const seen = []
    const { view } = mountEditor({ value: body, schemes, extensions: [livePreview({ resolveAttachment })], onChange: (b) => seen.push(b) })
    await settle()
    expect(previewModeOf(view.state)).toBe('preview')
    const on = bodyOf(view.state)
    act(() => switchPreviewMode(view, 'source'))
    const off = bodyOf(view.state)
    act(() => switchPreviewMode(view, 'preview'))
    await settle()
    expect(on).toBe(body)
    expect(off).toBe(body)
    expect(bodyOf(view.state)).toBe(body)
    expect(seen).toEqual([])
  })

  it.each(['preview', 'source'])('survives insert + delete of one character in %s mode', async (mode) => {
    const seen = []
    const { view } = mountEditor({ value: body, schemes, extensions: [livePreview({ resolveAttachment, mode })], onChange: (b) => seen.push(b) })
    await settle()
    const at = Math.min(2, view.state.doc.length)
    act(() => view.dispatch({ changes: { from: at, insert: 'x' }, userEvent: 'input.type' }))
    act(() => view.dispatch({ changes: { from: at, to: at + 1 }, userEvent: 'delete.backward' }))
    await settle()
    expect(seen).toHaveLength(2)
    expect(seen[1]).toBe(body)
    expect(bodyOf(view.state)).toBe(body)
  })

  it('walks the cursor through every line without changing the document', async () => {
    const { view } = mountEditor({ value: body, schemes, extensions: [livePreview({ resolveAttachment })] })
    await settle()
    for (let n = 1; n <= view.state.doc.lines; n += 7) {
      act(() => view.dispatch({ selection: { anchor: view.state.doc.line(n).from } }))
    }
    await settle()
    expect(bodyOf(view.state)).toBe(body)
  })
})

it('draws something on the corpus: the gate is not passing because the layer did nothing', async () => {
  const { container } = mountEditor({ value: FIXTURES['the masterclass-shaped note'], extensions: [livePreview({ resolveAttachment })] })
  await settle()
  expect(container.querySelectorAll('.cm-line[class*="arpn-lp-h"]').length).toBeGreaterThan(0)
  expect(container.querySelectorAll('.arpn-lp-mark').length).toBeGreaterThan(0)
})

it('finds the corpus images (jsdom draws only the first screenful, so this reads the whole state)', () => {
  const state = EditorState.create({ doc: FIXTURES['the masterclass-shaped note'], extensions: [markdownLanguage.extension] })
  let widgets = 0
  previewDecorations(state, { imageWidget: () => new (class extends WidgetType {})() }).between(0, state.doc.length, (_f, _t, d) => {
    if (d.spec.widget) widgets += 1
  })
  expect(widgets).toBe(15)
})
