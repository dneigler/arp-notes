// @vitest-environment jsdom
// CI GATE (C6d, ADR D4): the document is the string the writer typed. The spike's 33-construct corpus and a
// masterclass-shaped synthetic note survive one inserted and one deleted character byte for byte, through the
// whole editor (language, chips, autocomplete, upload handlers and all), with and without link schemes.
import { afterEach, describe, expect, it } from 'vitest'
import { bodyOf, createEditorState, editorExtensions } from '../src/editor/index.js'
import { createCompartments } from '../src/editor/core.js'
import { act, cleanup, fixtureText } from './helpers.js'
import { mountEditor, settle } from './editor-helpers.js'
import { EDITOR_STRINGS } from '../src/editor/strings.js'

afterEach(cleanup)

const FIXTURES = {
  'the spike 33-construct corpus': fixtureText('obsidian-synthetic.md'),
  'the masterclass-shaped note': fixtureText('masterclass-shaped.md'),
  'a CRLF note': fixtureText('obsidian-synthetic.md').replace(/\n/g, '\r\n'),
  'a note with a trailing newline': `${fixtureText('masterclass-shaped.md')}\n`,
  'the empty note': '',
}

const schemes = [
  { prefix: 'ex', search: () => [], resolve: (type, id) => (id === 35 ? { title: 'Études, Op. 99' } : null) },
  { prefix: 'pt', search: () => [], resolve: () => null },
]

function editorState(body, withSchemes) {
  return createEditorState(
    body,
    editorExtensions({
      getSchemes: () => (withSchemes ? schemes : []),
      getStrings: () => EDITOR_STRINGS,
      uploads: { handleFiles: () => false },
      compartments: createCompartments(),
      ariaLabel: 'Note',
      onUpdate: () => {},
    }),
  )
}

describe.each(Object.entries(FIXTURES))('%s', (_name, body) => {
  it.each([true, false])('state: insert + delete of one character is byte-identical (schemes: %s)', (withSchemes) => {
    let state = editorState(body, withSchemes)
    expect(bodyOf(state)).toBe(body)
    const at = Math.min(2, state.doc.length)
    state = state.update({ changes: { from: at, insert: 'x' } }).state
    state = state.update({ changes: { from: at, to: at + 1 } }).state
    expect(bodyOf(state)).toBe(body)
  })

  it('mounted editor: typing a character and deleting it reports the original body', async () => {
    const seen = []
    const { view } = mountEditor({ value: body, schemes, onChange: (b) => seen.push(b) })
    await settle()
    expect(bodyOf(view.state)).toBe(body)
    const at = Math.min(2, view.state.doc.length)
    act(() => view.dispatch({ changes: { from: at, insert: 'x' }, userEvent: 'input.type' }))
    act(() => view.dispatch({ changes: { from: at, to: at + 1 }, userEvent: 'delete.backward' }))
    await settle()
    expect(seen).toHaveLength(2)
    expect(seen[1]).toBe(body)
    expect(bodyOf(view.state)).toBe(body)
  })

  it('mounting alone never calls onChange', async () => {
    const seen = []
    mountEditor({ value: body, schemes, onChange: (b) => seen.push(b) })
    await settle()
    expect(seen).toEqual([])
  })
})

it('the masterclass-shaped fixture has the shape the spike measured', () => {
  const body = FIXTURES['the masterclass-shaped note']
  expect(body.match(/!\[\[[^\]]+\]\]/g)).toHaveLength(15)
  expect(body).toMatch(/!\[\[[^\]]+\|438x282\]\]/)
  expect(body).toMatch(/^\t+- /m)
  expect(body.match(/```dataview/g)).toHaveLength(3)
  expect(body).toMatch(/^duration:: 95$/m)
  expect(body.length).toBeGreaterThan(9000)
})
