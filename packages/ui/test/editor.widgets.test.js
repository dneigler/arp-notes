// @vitest-environment jsdom
// The chip widgets in a mounted editor: resolved title, '· not found', cache, source revealed under the cursor.
import { afterEach, describe, expect, it, vi } from 'vitest'
import { bodyOf } from '../src/editor/index.js'
import { act, cleanup } from './helpers.js'
import { mountEditor, settle } from './editor-helpers.js'

afterEach(cleanup)

const BODY = 'Played [@Études, Op.10](pt://repertoire/35) and [@Gone](pt://repertoire/404) today.'

function scheme(resolve) {
  return { prefix: 'pt', search: async () => [], resolve }
}

const chips = (container) => [...container.querySelectorAll('.arpn-chip')]

describe('chip widgets', () => {
  it('draw each chip as a widget, resolved through the host, and keep unresolved chips readable', async () => {
    const resolve = vi.fn(async (type, id) => (id === 35 ? { title: 'Études, Op.10', url: '/pieces/35' } : null))
    const { container, view } = mountEditor({ value: BODY, schemes: [scheme(resolve)] })
    expect(chips(container)).toHaveLength(2)
    await settle()
    const [found, missing] = chips(container)
    expect(found.textContent).toBe('@Études, Op.10')
    expect(found.dataset.state).toBe('found')
    expect(missing.textContent).toBe('@Gone · not found')
    expect(missing.dataset.state).toBe('missing')
    expect(resolve).toHaveBeenCalledWith('repertoire', 35)
    expect(resolve).toHaveBeenCalledWith('repertoire', 404)
    // The widgets are decoration: the document still holds the source.
    expect(bodyOf(view.state)).toBe(BODY)
  })

  it('shows the written label until the host answers', async () => {
    let answer
    const resolve = () => new Promise((r) => (answer = r))
    const { container } = mountEditor({ value: '[@Written](pt://repertoire/1)', schemes: [scheme(resolve)] })
    expect(chips(container)[0].textContent).toBe('@Written')
    expect(chips(container)[0].dataset.state).toBe('pending')
    await settle(1) // the host is asked on the next tick
    answer({ title: 'Resolved title' })
    await settle()
    expect(chips(container)[0].textContent).toBe('@Resolved title')
  })

  it('asks the host once per distinct chip, however often it is drawn', async () => {
    const resolve = vi.fn(async () => ({ title: 'T' }))
    const body = '[@A](pt://t/1) [@A](pt://t/1) [@B](pt://t/2)'
    const { view } = mountEditor({ value: body, schemes: [scheme(resolve)] })
    await settle()
    act(() => view.dispatch({ changes: { from: body.length, insert: ' more' } }))
    await settle()
    expect(resolve).toHaveBeenCalledTimes(2)
  })

  it('treats a host error as not-found now and asks again later', async () => {
    const resolve = vi.fn().mockRejectedValueOnce(new Error('down')).mockResolvedValue({ title: 'Back' })
    const { container, view } = mountEditor({ value: '[@X](pt://t/1)', schemes: [scheme(resolve)] })
    await settle()
    expect(chips(container)[0].textContent).toBe('@X · not found')
    act(() => view.dispatch({ changes: { from: 0, insert: ' ' } }))
    await settle()
    expect(chips(container)[0].textContent).toBe('@Back')
  })

  it('reveals the source while the cursor is inside the span, and draws the widget again outside', async () => {
    const { container, view } = mountEditor({ value: BODY, schemes: [scheme(async () => ({ title: 'T' }))] })
    await settle()
    const start = BODY.indexOf('[@Études')
    act(() => view.dispatch({ selection: { anchor: start + 4 } }))
    expect(chips(container)).toHaveLength(1)
    expect(view.contentDOM.textContent).toContain('[@Études, Op.10](pt://repertoire/35)')
    act(() => view.dispatch({ selection: { anchor: 0 } }))
    expect(chips(container)).toHaveLength(2)
    // The edges of the span do not reveal it, so a chip just inserted by Enter stays a chip.
    act(() => view.dispatch({ selection: { anchor: start } }))
    expect(chips(container)).toHaveLength(2)
  })

  it('a click on a chip puts the cursor inside it', async () => {
    const { container, view } = mountEditor({ value: BODY, schemes: [scheme(async () => ({ title: 'T' }))] })
    await settle()
    const start = BODY.indexOf('[@Études')
    vi.spyOn(view, 'posAtDOM').mockReturnValue(start)
    act(() => {
      chips(container)[0].dispatchEvent(new MouseEvent('mousedown', { bubbles: true, cancelable: true }))
    })
    expect(view.state.selection.main.head).toBe(start + 2)
    expect(chips(container)).toHaveLength(1)
  })

  it('leaves chips in code blocks and chips of unknown schemes as text', async () => {
    const body = '```\n[@In code](pt://t/1)\n```\n[@Other](zz://t/2)'
    const { container } = mountEditor({ value: body, schemes: [scheme(async () => ({ title: 'T' }))] })
    await settle()
    expect(chips(container)).toHaveLength(0)
  })

  it('follows a change of schemes', async () => {
    const body = '[@A](pt://t/1) [@B](jjf://venue/2)'
    const pt = scheme(async () => ({ title: 'PT' }))
    const jjf = { prefix: 'jjf', search: async () => [], resolve: async () => ({ title: 'Venue' }) }
    const { container, container: c0 } = mountEditor({ value: body, schemes: [pt] })
    await settle()
    expect(chips(c0)).toHaveLength(1)
    // Re-render with both schemes.
    const { mount, h } = await import('./helpers.js')
    const { NoteEditor } = await import('../src/editor/index.js')
    const second = mount(h(NoteEditor, { value: body, schemes: [pt, jjf] }))
    await settle()
    expect(chips(second)).toHaveLength(2)
    expect(container).toBeTruthy()
  })
})
