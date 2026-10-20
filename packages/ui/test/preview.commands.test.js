// @vitest-environment jsdom
// What the toolbar buttons write into the document.
import { completionStatus } from '@codemirror/autocomplete'
import { EditorSelection } from '@codemirror/state'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { bodyOf } from '../src/editor/index.js'
import { addImageFiles, insertWikiLink, toggleBold, toggleBulletList, toggleHeading, toggleItalic } from '../src/preview/index.js'
import { act, cleanup } from './helpers.js'
import { file, mountEditor, settle } from './editor-helpers.js'

afterEach(cleanup)

/** An editor holding `doc`, selection `[anchor, head]` (head defaults to anchor). */
function editor(doc, anchor = 0, head = anchor, props = {}) {
  const mounted = mountEditor({ value: doc, ...props })
  act(() => mounted.view.dispatch({ selection: EditorSelection.single(anchor, head) }))
  return mounted.view
}

const run = (command, view) => act(() => command(view))
const sel = (view) => [view.state.selection.main.anchor, view.state.selection.main.head]
const caret = (doc, marker = '|') => ({ doc: doc.replace(marker, ''), at: doc.indexOf(marker) })

describe('Heading', () => {
  it('puts ## at the start of the line and takes it off again', () => {
    const view = editor('Title', 3)
    run(toggleHeading, view)
    expect(bodyOf(view.state)).toBe('## Title')
    expect(sel(view)).toEqual([6, 6])
    run(toggleHeading, view)
    expect(bodyOf(view.state)).toBe('Title')
    expect(sel(view)).toEqual([3, 3])
  })

  it('a caret at the very start ends up after the new marker', () => {
    const view = editor('Title', 0)
    run(toggleHeading, view)
    expect(sel(view)).toEqual([3, 3])
  })

  it('turns another level into ##, and does it for every selected line', () => {
    const view = editor('### Deep\nplain\n# Top\nuntouched', 2, 20)
    run(toggleHeading, view)
    expect(bodyOf(view.state)).toBe('## Deep\n## plain\n## Top\nuntouched')
  })

  it('does not reach a line the selection only touches the start of', () => {
    const view = editor('one\ntwo\nthree', 0, 8)
    run(toggleHeading, view)
    expect(bodyOf(view.state)).toBe('## one\n## two\nthree')
  })

  it('works on an empty line and in an empty note', () => {
    const view = editor('', 0)
    run(toggleHeading, view)
    expect(bodyOf(view.state)).toBe('## ')
    expect(sel(view)).toEqual([3, 3])
  })
})

describe('Bold and Italic', () => {
  it('wraps a selection and keeps the text selected', () => {
    const view = editor('say hello now', 4, 9)
    run(toggleBold, view)
    expect(bodyOf(view.state)).toBe('say **hello** now')
    expect(sel(view)).toEqual([6, 11])
    run(toggleBold, view)
    expect(bodyOf(view.state)).toBe('say hello now')
    expect(sel(view)).toEqual([4, 9])
  })

  it('wraps with a single * for Italic', () => {
    const view = editor('say hello now', 4, 9)
    run(toggleItalic, view)
    expect(bodyOf(view.state)).toBe('say *hello* now')
    expect(sel(view)).toEqual([5, 10])
    run(toggleItalic, view)
    expect(bodyOf(view.state)).toBe('say hello now')
  })

  it('takes the marks off a selection that includes them', () => {
    const view = editor('say **hello** now', 4, 13)
    run(toggleBold, view)
    expect(bodyOf(view.state)).toBe('say hello now')
    expect(sel(view)).toEqual([4, 9])
  })

  it('a caret inside a word marks the word and keeps the caret in place', () => {
    const { doc, at } = caret('say hel|lo now')
    const view = editor(doc, at)
    run(toggleBold, view)
    expect(bodyOf(view.state)).toBe('say **hello** now')
    expect(sel(view)).toEqual([at + 2, at + 2])
    run(toggleBold, view)
    expect(bodyOf(view.state)).toBe(doc)
    expect(sel(view)).toEqual([at, at])
  })

  it('a caret between spaces opens an empty pair with the caret inside', () => {
    const view = editor('a  b', 2)
    run(toggleBold, view)
    expect(bodyOf(view.state)).toBe('a **** b')
    expect(sel(view)).toEqual([4, 4])
    const italic = editor('a  b', 2)
    run(toggleItalic, italic)
    expect(bodyOf(italic.state)).toBe('a ** b')
    expect(sel(italic)).toEqual([3, 3])
  })

  it('tells bold from italic: italic over **x** adds, it does not strip one asterisk of the bold', () => {
    const view = editor('**x**', 2, 3)
    run(toggleItalic, view)
    expect(bodyOf(view.state)).toBe('***x***')
    run(toggleBold, view)
    expect(bodyOf(view.state)).toBe('*x*')
    run(toggleItalic, view)
    expect(bodyOf(view.state)).toBe('x')
  })

  it('keeps a backwards selection backwards', () => {
    const view = editor('say hello now', 9, 4)
    run(toggleBold, view)
    expect(sel(view)).toEqual([11, 6])
  })
})

describe('Bulleted list', () => {
  it('adds "- " to the line and takes it off again', () => {
    const view = editor('item', 2)
    run(toggleBulletList, view)
    expect(bodyOf(view.state)).toBe('- item')
    expect(sel(view)).toEqual([4, 4])
    run(toggleBulletList, view)
    expect(bodyOf(view.state)).toBe('item')
  })

  it('goes after the indentation, and skips blank lines of a multi-line selection', () => {
    const view = editor('a\n\n  b', 0, 6)
    run(toggleBulletList, view)
    expect(bodyOf(view.state)).toBe('- a\n\n  - b')
    run(toggleBulletList, view)
    expect(bodyOf(view.state)).toBe('a\n\n  b')
  })

  it('adds the marker only to the lines that lack one', () => {
    const view = editor('* kept\nnew', 0, 10)
    run(toggleBulletList, view)
    expect(bodyOf(view.state)).toBe('* kept\n- new')
  })

  it('a single empty line gets a bullet', () => {
    const view = editor('', 0)
    run(toggleBulletList, view)
    expect(bodyOf(view.state)).toBe('- ')
  })
})

describe('Link [[', () => {
  const catalogue = [{ entity_type: 'composer', entity_id: 13, entity_label: 'Chopin' }]
  const scheme = { prefix: 'ex', search: async () => catalogue, resolve: async () => ({ title: 'Chopin' }) }

  it('inserts [[ at the caret and opens the autocomplete', async () => {
    const view = editor('See  now', 4, 4, { schemes: [scheme] })
    run(insertWikiLink, view)
    expect(bodyOf(view.state)).toBe('See [[ now')
    expect(sel(view)).toEqual([6, 6])
    await vi.waitFor(() => expect(document.querySelector('.cm-tooltip-autocomplete .cm-completionLabel')?.textContent).toBe('Chopin'))
    expect(completionStatus(view.state)).toBe('active')
  })

  it('a selection becomes the search text', async () => {
    const view = editor('See Chop now', 4, 8, { schemes: [scheme] })
    run(insertWikiLink, view)
    expect(bodyOf(view.state)).toBe('See [[Chop now')
    expect(sel(view)).toEqual([10, 10])
    await vi.waitFor(() => expect(document.querySelector('.arpn-wiki-head')?.textContent).toBe('Link to · “Chop”'))
  })

  it('Enter on the chosen row writes the house chip', async () => {
    const view = editor('', 0, 0, { schemes: [scheme] })
    run(insertWikiLink, view)
    await vi.waitFor(() => expect(document.querySelector('.cm-tooltip-autocomplete [role=option]')).not.toBeNull())
    // CodeMirror ignores Enter for 75 ms after a popover appears.
    await new Promise((r) => setTimeout(r, 120))
    act(() => view.contentDOM.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', keyCode: 13, bubbles: true, cancelable: true })))
    expect(bodyOf(view.state)).toBe('[@Chopin](ex://composer/13)')
  })
})

describe('Image', () => {
  const caps = { protocol: 1, attachments: true, mime_allowlist: ['image/png'], limits: { max_attachment_bytes: 1e7 } }

  it('hands picked files to the editor’s own upload path: placeholder in the document, upload called', async () => {
    const upload = vi.fn(() => new Promise(() => {}))
    const view = editor('Look: ', 6, 6, { capabilities: caps, upload })
    const png = file('IMG_2041.png', 'image/png', 4096)
    expect(addImageFiles(view, [png])).toBe(true)
    expect(upload).toHaveBeenCalledWith(png, expect.objectContaining({ onProgress: expect.any(Function) }))
    expect(bodyOf(view.state)).toMatch(/^Look: !\[uploading IMG_2041\.png…\]\(attachment:\/\/pending-[a-z0-9]+\)$/)
  })

  it('inserts at the selection', () => {
    const view = editor('ab', 1, 1, { capabilities: caps, upload: () => new Promise(() => {}) })
    addImageFiles(view, [file('x.png', 'image/png', 10)])
    expect(bodyOf(view.state)).toMatch(/^a!\[uploading x\.png…\]\(attachment:\/\/pending-[a-z0-9]+\)b$/)
  })

  it('on an app that takes no attachments the policy dialog explains and the text is unchanged', async () => {
    const view = editor('Look: ', 6, 6, { capabilities: { ...caps, attachments: false }, upload: vi.fn() })
    addImageFiles(view, [file('IMG.png', 'image/png', 10)])
    await settle()
    expect(bodyOf(view.state)).toBe('Look: ')
    expect(document.body.textContent).toContain('Image not added')
  })

  it('does nothing without files', () => {
    const view = editor('x', 0)
    expect(addImageFiles(view, [])).toBe(false)
    expect(addImageFiles(view, null)).toBe(false)
  })
})
