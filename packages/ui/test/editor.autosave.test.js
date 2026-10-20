// @vitest-environment jsdom
// Autosave: debounced 1.5 s, the house envelope, conflict -> onConflict(server) (ADR A.2 autosave).
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { AUTOSAVE_DEBOUNCE_MS, createAutosaver } from '../src/editor/autosave.js'
import { act, cleanup } from './helpers.js'
import { bodyOf } from '../src/editor/index.js'
import { deferred, file, mountControlled, mountEditor, pasteFiles } from './editor-helpers.js'

afterEach(cleanup)
beforeEach(() => vi.useFakeTimers())
afterEach(() => vi.useRealTimers())

const flush = async (ms = 0) => {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms)
  })
}
const edit = (view, text) => act(() => view.dispatch({ changes: { from: view.state.doc.length, insert: text }, userEvent: 'input.type' }))
const ok = (version) => ({ note: { id: 1, version } })

describe('createAutosaver', () => {
  function make(save, extra = {}) {
    const states = []
    const onConflict = vi.fn()
    const saver = createAutosaver({ body: 'a', version: 3, getHandlers: () => ({ save, onConflict }), onState: (s) => states.push(s), ...extra })
    return { saver, states, onConflict }
  }

  it('waits 1.5 s after the last edit and sends the latest body once', async () => {
    const save = vi.fn(async () => ok(4))
    const { saver, states } = make(save)
    saver.edit('ab')
    await vi.advanceTimersByTimeAsync(1000)
    saver.edit('abc')
    await vi.advanceTimersByTimeAsync(1499)
    expect(save).not.toHaveBeenCalled()
    await vi.advanceTimersByTimeAsync(1)
    expect(save).toHaveBeenCalledTimes(1)
    expect(save).toHaveBeenCalledWith('abc', 3)
    expect(states).toEqual(['dirty', 'saving', 'saved'])
    expect(saver.version).toBe(4)
    expect(AUTOSAVE_DEBOUNCE_MS).toBe(1500)
  })

  it('does not save when the text went back to what is saved', async () => {
    const save = vi.fn(async () => ok(4))
    const { saver, states } = make(save)
    saver.edit('ab')
    saver.edit('a')
    await vi.advanceTimersByTimeAsync(5000)
    expect(save).not.toHaveBeenCalled()
    expect(states.at(-1)).toBe('saved')
  })

  it('saves again after a save that was in flight when more edits arrived', async () => {
    const first = deferred()
    const save = vi.fn().mockReturnValueOnce(first.promise).mockResolvedValue(ok(5))
    const { saver } = make(save)
    saver.edit('ab')
    await vi.advanceTimersByTimeAsync(1500)
    saver.edit('abc')
    await vi.advanceTimersByTimeAsync(1500) // timer fires while the first save is still out
    expect(save).toHaveBeenCalledTimes(1)
    first.resolve(ok(4))
    await vi.advanceTimersByTimeAsync(1500)
    expect(save).toHaveBeenCalledTimes(2)
    expect(save).toHaveBeenLastCalledWith('abc', 4)
  })

  it('a conflict hands the envelope to onConflict and stops saving', async () => {
    const envelope = { conflict: true, server_version: 9, server_data: { id: 1, body_md: 'theirs' } }
    const save = vi.fn(async () => envelope)
    const { saver, states, onConflict } = make(save)
    saver.edit('mine')
    await vi.advanceTimersByTimeAsync(1500)
    expect(onConflict).toHaveBeenCalledWith(envelope)
    expect(states.at(-1)).toBe('conflict')
    saver.edit('mine, more')
    await vi.advanceTimersByTimeAsync(10_000)
    expect(save).toHaveBeenCalledTimes(1)
  })

  it('keep mine: a new version resumes with the pending body', async () => {
    const save = vi.fn().mockResolvedValueOnce({ conflict: true, server_version: 9 }).mockResolvedValue(ok(10))
    const { saver } = make(save)
    saver.edit('mine')
    await vi.advanceTimersByTimeAsync(1500)
    saver.setVersion(9)
    await vi.advanceTimersByTimeAsync(0)
    expect(save).toHaveBeenLastCalledWith('mine', 9)
  })

  it('take theirs: reset makes the server body the baseline', async () => {
    const save = vi.fn().mockResolvedValueOnce({ conflict: true, server_version: 9 }).mockResolvedValue(ok(10))
    const { saver, states } = make(save)
    saver.edit('mine')
    await vi.advanceTimersByTimeAsync(1500)
    saver.reset('theirs', 9)
    saver.edit('theirs')
    await vi.advanceTimersByTimeAsync(5000)
    expect(save).toHaveBeenCalledTimes(1)
    expect(states.at(-1)).toBe('idle')
    saver.edit('theirs!')
    await vi.advanceTimersByTimeAsync(1500)
    expect(save).toHaveBeenLastCalledWith('theirs!', 9)
  })

  it('a failed save reports an error and retries', async () => {
    const save = vi.fn().mockRejectedValueOnce(new Error('offline')).mockResolvedValue(ok(4))
    const { saver, states } = make(save)
    saver.edit('ab')
    await vi.advanceTimersByTimeAsync(1500)
    expect(states.at(-1)).toBe('error')
    await vi.advanceTimersByTimeAsync(5000)
    expect(save).toHaveBeenCalledTimes(2)
    expect(states.at(-1)).toBe('saved')
  })

  it('flush saves what is waiting; dispose silences it', async () => {
    const save = vi.fn(async () => ok(4))
    const { saver, states } = make(save)
    saver.edit('ab')
    saver.flush()
    await vi.advanceTimersByTimeAsync(0)
    expect(save).toHaveBeenCalledWith('ab', 3)
    saver.dispose()
    saver.edit('abc')
    await vi.advanceTimersByTimeAsync(5000)
    expect(save).toHaveBeenCalledTimes(1)
    expect(states.at(-1)).toBe('saved')
  })
})

describe('NoteEditor autosave', () => {
  it('saves the body with the house envelope 1.5 s after typing and reports status', async () => {
    const save = vi.fn(async () => ok(8))
    const onStatus = vi.fn()
    const { view, container } = mountEditor({ value: 'Hello', autosave: { save, version: 7 }, onStatus })
    edit(view, ' world')
    await flush(1499)
    expect(save).not.toHaveBeenCalled()
    await flush(1)
    expect(save).toHaveBeenCalledWith('Hello world', 7)
    expect(onStatus).toHaveBeenLastCalledWith({ save: 'saved', version: 8, uploads: [] })
    expect(container.querySelector('[data-arpn=save-status]').textContent).toBe('Saved')
  })

  it('is off without an autosave prop', async () => {
    const onChange = vi.fn()
    const { view, container } = mountEditor({ value: 'Hello', onChange })
    edit(view, '!')
    await flush(5000)
    expect(onChange).toHaveBeenCalledWith('Hello!')
    expect(container.querySelector('[data-arpn=save-status]')).toBeNull()
  })

  it('calls onConflict with the server envelope and shows it', async () => {
    const envelope = { conflict: true, server_version: 12, server_data: { id: 1, body_md: 'theirs', version: 12 } }
    const onConflict = vi.fn()
    const { view, container } = mountEditor({ value: 'a', autosave: { save: async () => envelope, version: 5, onConflict } })
    edit(view, 'b')
    await flush(1500)
    expect(onConflict).toHaveBeenCalledWith(envelope)
    expect(container.querySelector('[data-arpn=save-status]').textContent).toBe('Edited somewhere else — not saved')
  })

  it('never sends an upload placeholder', async () => {
    const save = vi.fn(async () => ok(2))
    const gate = deferred()
    const caps = { attachments: true, mime_allowlist: null, limits: { max_attachment_bytes: 1e9 } }
    const { view } = mountEditor({ value: 'Intro ', capabilities: caps, upload: () => gate.promise, autosave: { save, version: 1 } })
    act(() => view.dispatch({ selection: { anchor: 6 } }))
    pasteFiles(view.contentDOM, [file('a.png')])
    edit(view, ' tail')
    await flush(1500)
    expect(save).toHaveBeenCalledTimes(1)
    expect(save.mock.calls[0][0]).toBe('Intro  tail')
    gate.resolve({ blob_id: 4, filename: 'a.png' })
    await flush(1500)
    expect(save).toHaveBeenLastCalledWith('Intro ![a.png](attachment://4) tail', 2)
  })

  it('a new value from the host (take theirs) replaces the text without onChange, and is not saved back', async () => {
    const save = vi.fn(async () => ok(13))
    const onChange = vi.fn()
    const ed = mountControlled({ value: 'mine', onChange, autosave: { save, version: 5 } })
    edit(ed.view, ' edit')
    onChange.mockClear()
    ed.update({ value: 'theirs', autosave: { save, version: 12 } })
    expect(bodyOf(ed.view.state)).toBe('theirs')
    expect(onChange).not.toHaveBeenCalled()
    await flush(5000)
    expect(save).not.toHaveBeenCalled()
    edit(ed.view, '!')
    await flush(1500)
    expect(save).toHaveBeenCalledWith('theirs!', 12)
  })

  it('ignores the host echoing back what onChange just reported', async () => {
    const ed = mountControlled({ value: '' })
    ed.update({ onChange: (b) => ed.update({ value: b }) })
    edit(ed.view, 'a')
    edit(ed.view, 'b')
    edit(ed.view, 'c')
    // A stale echo of an earlier value does not rewind the editor.
    ed.update({ value: 'ab' })
    expect(bodyOf(ed.view.state)).toBe('abc')
  })

  it('keep mine: a new autosave.version after a conflict resumes saving', async () => {
    const save = vi.fn().mockResolvedValueOnce({ conflict: true, server_version: 9, server_data: {} }).mockResolvedValue(ok(10))
    const ed = mountControlled({ value: 'a', autosave: { save, version: 5, onConflict: () => {} } })
    edit(ed.view, 'b')
    await flush(1500)
    expect(save).toHaveBeenCalledTimes(1)
    ed.update({ autosave: { save, version: 9, onConflict: () => {} } })
    await flush(0)
    expect(save).toHaveBeenLastCalledWith('ab', 9)
  })

  it('flushes a pending save when it unmounts', async () => {
    const save = vi.fn(async () => ok(2))
    const { view } = mountEditor({ value: 'a', autosave: { save, version: 1 } })
    edit(view, 'b')
    cleanup()
    await flush(0)
    expect(save).toHaveBeenCalledWith('ab', 1)
  })
})
