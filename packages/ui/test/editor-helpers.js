// Test helpers for the CodeMirror editor under jsdom, which has no layout: Range geometry and
// elementFromPoint are missing, and CodeMirror measures with both.
import { EditorView } from '@codemirror/view'
import { useState } from 'react'
import { act, h, mount } from './helpers.js'
import { NoteEditor } from '../src/editor/index.js'

const emptyRects = () => {
  const list = []
  list.item = () => null
  return list
}
const zeroRect = () => ({ x: 0, y: 0, width: 0, height: 0, top: 0, left: 0, right: 0, bottom: 0, toJSON() {} })

export function polyfillLayout() {
  Range.prototype.getClientRects ??= emptyRects
  Range.prototype.getBoundingClientRect ??= zeroRect
  document.elementFromPoint ??= () => null
  document.elementsFromPoint ??= () => []
}

polyfillLayout()

/** Mounts <NoteEditor/> and returns the container plus the live EditorView. */
export function mountEditor(props) {
  let view = null
  const container = mount(h(NoteEditor, { onReady: (v) => (view = v ?? view), ...props }))
  return { container, get view() { return view } }
}

export const viewOf = (container) => EditorView.findFromDOM(container.querySelector('.cm-editor'))

/** Types `text` at the cursor through the view, the way input events arrive (userEvent 'input.type'). */
export function type(view, text) {
  act(() => {
    const { from, to } = view.state.selection.main
    view.dispatch({ changes: { from, to, insert: text }, selection: { anchor: from + text.length }, userEvent: 'input.type' })
  })
}

/** Lets pending promises (resolve, search) settle inside act(). */
export async function settle(times = 3) {
  for (let i = 0; i < times; i += 1) {
    await act(async () => {
      await new Promise((r) => setTimeout(r, 0))
    })
  }
}

export function file(name, type = 'image/png', size = 2048) {
  const f = new File([new Uint8Array(Math.min(size, 16))], name, { type })
  Object.defineProperty(f, 'size', { value: size })
  return f
}

/** A paste event with `files` (and optional text) on the editor's content element. */
export function pasteFiles(target, files, text = '') {
  const event = new Event('paste', { bubbles: true, cancelable: true })
  event.clipboardData = { files, items: [], types: text ? ['text/plain', 'Files'] : ['Files'], getData: (t) => (t === 'text/plain' ? text : '') }
  act(() => {
    target.dispatchEvent(event)
  })
  return event
}

export function dropFiles(target, files, at = { x: 5, y: 5 }) {
  const event = new Event('drop', { bubbles: true, cancelable: true })
  event.dataTransfer = { files, types: ['Files'], getData: () => '' }
  event.clientX = at.x
  event.clientY = at.y
  act(() => {
    target.dispatchEvent(event)
  })
  return event
}

/** A promise you resolve from the test, to hold an upload open. */
export function deferred() {
  let resolve
  let reject
  const promise = new Promise((res, rej) => {
    resolve = res
    reject = rej
  })
  return { promise, resolve, reject }
}

/** Like mountEditor, but the props can change afterwards: update({value, autosave, ...}). */
export function mountControlled(initial) {
  let setProps
  let view = null
  function Wrapper() {
    const [props, set] = useState(initial)
    setProps = set
    return h(NoteEditor, { onReady: (v) => (view = v ?? view), ...props })
  }
  const container = mount(h(Wrapper))
  return {
    container,
    get view() {
      return view
    },
    update: (patch) => act(() => setProps((p) => ({ ...p, ...patch }))),
  }
}
