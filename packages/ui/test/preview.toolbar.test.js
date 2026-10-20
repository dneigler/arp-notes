// @vitest-environment jsdom
// EditorToolbar and ModeToggle: the mockup's labels, 44 px targets, focus that stays in the editor, the phone
// bar pinned above the keyboard, and the Live preview | Source switch.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { Fragment, useState } from 'react'
import { NoteEditor } from '../src/editor/index.js'
import { EditorToolbar, ModeToggle, livePreview, previewModeOf, useKeyboardHeight } from '../src/preview/index.js'
import { act, cleanup, h, mount } from './helpers.js'
import { file, settle } from './editor-helpers.js'

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  document.body.replaceChildren()
})

const CAPS = { protocol: 1, attachments: true, mime_allowlist: ['image/png', 'application/pdf'], limits: { max_attachment_bytes: 1e7 } }

/** The editor with the toolbar above it, wired the way a host does it. */
function Desk({ toolbar = {}, editor = {}, value = 'Title\n' }) {
  const [view, setView] = useState(null)
  return h(Fragment, null, h(EditorToolbar, { view, capabilities: CAPS, ...toolbar }), h(NoteEditor, { value, onReady: (v) => setView(v), capabilities: CAPS, extensions: previewExtensions, ...editor }))
}
const previewExtensions = [livePreview()]

function setup(props) {
  return { container: mount(h(Desk, props)) }
}

const button = (container, action) => container.querySelector(`[data-action="${action}"]`)
const labels = (container) => [...container.querySelectorAll('[role=toolbar] [data-action]')].map((b) => b.getAttribute('aria-label'))

describe('desk toolbar', () => {
  it('carries the EditorDesk labels, in order, in a labelled toolbar', async () => {
    const { container } = setup({})
    await settle()
    const bar = container.querySelector('[role=toolbar]')
    expect(bar.getAttribute('aria-label')).toBe('Formatting')
    expect(labels(container)).toEqual(['Heading', 'Bold', 'Italic', 'Bulleted list', 'Link [[', 'Image'])
    expect(button(container, 'link').textContent).toBe('Link [[')
    expect(button(container, 'image').textContent).toBe('Image')
    expect(container.querySelector('[data-variant]').dataset.variant).toBe('desk')
  })

  it('makes every target at least 44 px', async () => {
    const { container } = setup({ toolbar: { mode: 'preview', onModeChange: () => {} } })
    await settle()
    const targets = container.querySelectorAll('button')
    expect(targets.length).toBeGreaterThanOrEqual(8)
    for (const t of targets) {
      expect(parseInt(t.style.minWidth, 10), t.outerHTML).toBeGreaterThanOrEqual(44)
      expect(parseInt(t.style.minHeight, 10), t.outerHTML).toBeGreaterThanOrEqual(44)
    }
  })

  it('writes Markdown into the editor and keeps the selection and focus there', async () => {
    const { container } = setup({ value: 'say hello now' })
    await settle()
    const content = container.querySelector('.cm-content')
    act(() => content.focus())
    const click = (action) => {
      const down = new MouseEvent('mousedown', { bubbles: true, cancelable: true })
      act(() => {
        button(container, action).dispatchEvent(down)
      })
      expect(down.defaultPrevented, `${action} must not take focus from the editor`).toBe(true)
      act(() => button(container, action).click())
    }
    click('heading')
    expect(content.textContent).toContain('## say hello now')
    click('heading')
    expect(content.textContent).not.toContain('##')
    click('list')
    expect(content.textContent).toContain('- say hello now')
  })

  it('is one tab stop; the arrow keys, Home and End move inside it', async () => {
    const { container } = setup({})
    await settle()
    const stops = () => [...container.querySelectorAll('[role=toolbar] button')].filter((b) => b.tabIndex === 0)
    expect(stops()).toHaveLength(1)
    expect(stops()[0].dataset.action).toBe('heading')
    const key = (name) => act(() => document.activeElement.dispatchEvent(new KeyboardEvent('keydown', { key: name, bubbles: true, cancelable: true })))
    act(() => button(container, 'heading').focus())
    key('ArrowRight')
    expect(document.activeElement.dataset.action).toBe('bold')
    expect(stops().map((b) => b.dataset.action)).toEqual(['bold'])
    key('End')
    expect(document.activeElement.dataset.action).toBe('image')
    key('ArrowRight')
    expect(document.activeElement.dataset.action).toBe('heading')
    key('ArrowLeft')
    expect(document.activeElement.dataset.action).toBe('image')
    key('Home')
    expect(document.activeElement.dataset.action).toBe('heading')
  })

  it('does nothing, and does not throw, before the editor is ready', () => {
    const container = mount(h(EditorToolbar, { view: null, capabilities: CAPS, variant: 'desk' }))
    expect(() => act(() => button(container, 'bold').click())).not.toThrow()
  })

  it('shows the mode toggle only when asked for', async () => {
    const without = setup({})
    await settle()
    expect(without.container.querySelector('[data-arpn=mode-toggle]')).toBeNull()
    cleanup()
    const withToggle = setup({ toolbar: { mode: 'preview', onModeChange: () => {} } })
    await settle()
    expect(withToggle.container.querySelector('[data-arpn=mode-toggle]')).not.toBeNull()
  })
})

describe('Image button', () => {
  it('opens a file picker limited to the capabilities’ types, and hands the files to the upload path', async () => {
    const upload = vi.fn(() => new Promise(() => {}))
    const { container } = setup({ editor: { upload } })
    await settle()
    const input = container.querySelector('[data-arpn=image-picker]')
    expect(input.accept).toBe('image/png,application/pdf')
    const open = vi.spyOn(input, 'click')
    act(() => button(container, 'image').click())
    expect(open).toHaveBeenCalledTimes(1)

    const png = file('IMG_2041.png', 'image/png', 4096)
    Object.defineProperty(input, 'files', { value: [png], configurable: true })
    act(() => {
      input.dispatchEvent(new Event('change', { bubbles: true }))
    })
    expect(upload).toHaveBeenCalledWith(png, expect.objectContaining({ onProgress: expect.any(Function) }))
    expect(container.querySelector('.cm-content').textContent).toContain('![uploading IMG_2041.png…](attachment://pending-')
  })

  it('falls back to any image when the host lists no types', async () => {
    const { container } = setup({ toolbar: { capabilities: { ...CAPS, mime_allowlist: null } } })
    await settle()
    expect(container.querySelector('[data-arpn=image-picker]').accept).toBe('image/*')
  })

  it('is dimmed and says so when the app takes no attachments; it opens nothing', async () => {
    const { container } = setup({ toolbar: { capabilities: { ...CAPS, attachments: false } } })
    await settle()
    const image = button(container, 'image')
    expect(image.getAttribute('aria-label')).toBe('Image, unavailable: attachments are off')
    expect(image.getAttribute('aria-disabled')).toBe('true')
    expect(image.disabled).toBe(false) // stays reachable by keyboard and screen reader
    const open = vi.spyOn(container.querySelector('[data-arpn=image-picker]'), 'click')
    act(() => image.click())
    expect(open).not.toHaveBeenCalled()
  })
})

describe('Live preview | Source toggle', () => {
  it('is a labelled group of two toggle buttons showing the current mode', () => {
    const container = mount(h(ModeToggle, { mode: 'preview' }))
    const group = container.querySelector('[role=group]')
    expect(group.getAttribute('aria-label')).toBe('Editor mode')
    const [live, source] = [...group.querySelectorAll('button')]
    expect(live.textContent).toBe('Live preview')
    expect(source.textContent).toBe('Source')
    expect([live.getAttribute('aria-pressed'), source.getAttribute('aria-pressed')]).toEqual(['true', 'false'])
  })

  it('switches the editor’s layer and keeps selection and text', async () => {
    const seen = []
    const { container } = setup({ toolbar: { mode: undefined, onModeChange: (m) => seen.push(m) }, value: '# Title\n\nbody' })
    await settle()
    expect(container.querySelectorAll('.cm-line.arpn-lp-h1')).toHaveLength(1)
    const [live, source] = [...container.querySelectorAll('[data-arpn=mode-toggle] button')]
    expect(live.getAttribute('aria-pressed')).toBe('true')
    act(() => source.click())
    expect(seen).toEqual(['source'])
    expect(container.querySelectorAll('[class*="arpn-lp-"]')).toHaveLength(0)
    expect(source.getAttribute('aria-pressed')).toBe('true')
    act(() => live.click())
    expect(seen).toEqual(['source', 'preview'])
    expect(container.querySelectorAll('.cm-line.arpn-lp-h1')).toHaveLength(1)
    expect(container.querySelector('.cm-content').textContent).toContain('# Title')
  })

  it('does not take focus from the editor', () => {
    const container = mount(h(ModeToggle, { mode: 'preview' }))
    const down = new MouseEvent('mousedown', { bubbles: true, cancelable: true })
    container.querySelector('button').dispatchEvent(down)
    expect(down.defaultPrevented).toBe(true)
  })

  it('a controlled toggle follows its mode prop, an uncontrolled one keeps its own', () => {
    const controlled = mount(h(ModeToggle, { mode: 'source', onChange: () => {} }))
    act(() => controlled.querySelector('[data-mode=preview]').click())
    expect(controlled.querySelector('[data-mode=source]').getAttribute('aria-pressed')).toBe('true')
    const own = mount(h(ModeToggle, { defaultMode: 'source' }))
    expect(own.querySelector('[data-mode=source]').getAttribute('aria-pressed')).toBe('true')
    act(() => own.querySelector('[data-mode=preview]').click())
    expect(own.querySelector('[data-mode=preview]').getAttribute('aria-pressed')).toBe('true')
  })

  it('switches a view directly', async () => {
    let view = null
    mount(h(NoteEditor, { value: 'x', extensions: previewExtensions, onReady: (v) => (view = v ?? view) }))
    const container = mount(h(ModeToggle, { view, defaultMode: 'preview' }))
    act(() => container.querySelector('[data-mode=source]').click())
    expect(previewModeOf(view.state)).toBe('source')
  })
})

describe('phone bar', () => {
  it('uses the EditorPhone labels and Hide keyboard, pinned above the keyboard', async () => {
    const { container } = setup({ toolbar: { variant: 'phone', alwaysVisible: true, keyboardHeight: 300 } })
    await settle()
    const bar = container.querySelector('[data-variant=phone]')
    expect(bar.style.position).toBe('fixed')
    expect(bar.style.bottom).toBe('300px')
    expect(labels(container)).toEqual(['Heading', 'Bold', 'Italic', 'List', 'Insert link', 'Add image'])
    expect(button(container, 'hide-keyboard').textContent).toBe('Hide keyboard')
    expect(parseInt(button(container, 'hide-keyboard').style.minHeight, 10)).toBeGreaterThanOrEqual(44)
    // The desk bar's words are glyphs here.
    expect(button(container, 'link').textContent).toBe('[[')
    expect(button(container, 'image').textContent).toBe('')
  })

  it('appears only while the editor has focus and the keyboard is up', async () => {
    const { container } = setup({ toolbar: { variant: 'phone', keyboardHeight: 300 } })
    await settle()
    expect(container.querySelector('[data-variant=phone]')).toBeNull()
    act(() => container.querySelector('.cm-content').focus())
    expect(container.querySelector('[data-variant=phone]')).not.toBeNull()
    act(() => container.querySelector('.cm-content').blur())
    expect(container.querySelector('[data-variant=phone]')).toBeNull()
  })

  it('stays hidden with focus but no keyboard (a hardware keyboard)', async () => {
    const { container } = setup({ toolbar: { variant: 'phone', keyboardHeight: 0 } })
    await settle()
    act(() => container.querySelector('.cm-content').focus())
    expect(container.querySelector('[data-variant=phone]')).toBeNull()
  })

  it('Hide keyboard blurs the editor and the bar goes away', async () => {
    const { container } = setup({ toolbar: { variant: 'phone', keyboardHeight: 300 } })
    await settle()
    const content = container.querySelector('.cm-content')
    act(() => content.focus())
    act(() => button(container, 'hide-keyboard').click())
    expect(document.activeElement).not.toBe(content)
    expect(container.querySelector('[data-variant=phone]')).toBeNull()
  })

  it('the buttons still write Markdown', async () => {
    const { container } = setup({ toolbar: { variant: 'phone', alwaysVisible: true, keyboardHeight: 300 }, value: 'word' })
    await settle()
    act(() => button(container, 'bold').click())
    expect(container.querySelector('.cm-content').textContent).toContain('**word**')
  })

  it('"auto" is the phone bar under 600 px and the desk bar above', async () => {
    const mql = (matches) => ({ matches, addEventListener() {}, removeEventListener() {} })
    vi.stubGlobal('matchMedia', () => mql(true))
    const narrow = setup({ toolbar: { variant: 'auto', alwaysVisible: true, keyboardHeight: 300 } })
    await settle()
    expect(narrow.container.querySelector('[data-variant]').dataset.variant).toBe('phone')
    cleanup()
    vi.stubGlobal('matchMedia', () => mql(false))
    const wide = setup({ toolbar: { variant: 'auto' } })
    await settle()
    expect(wide.container.querySelector('[data-variant]').dataset.variant).toBe('desk')
  })
})

describe('useKeyboardHeight', () => {
  let vv

  beforeEach(() => {
    vv = Object.assign(new EventTarget(), { height: 800, offsetTop: 0 })
    vi.stubGlobal('visualViewport', vv)
    vi.stubGlobal('innerHeight', 800)
  })

  const Probe = ({ onHeight }) => {
    onHeight(useKeyboardHeight())
    return null
  }

  it('is the part of the layout viewport the visual viewport has lost, once it is keyboard-sized', () => {
    let height = -1
    mount(h(Probe, { onHeight: (n) => (height = n) }))
    expect(height).toBe(0)
    act(() => {
      vv.height = 480
      vv.dispatchEvent(new Event('resize'))
    })
    expect(height).toBe(320)
    act(() => {
      vv.height = 760 // a toolbar or an address bar, not a keyboard
      vv.dispatchEvent(new Event('resize'))
    })
    expect(height).toBe(0)
  })

  it('discounts the visual viewport’s own scroll, so the bar lands on the keyboard’s top edge', () => {
    let height = -1
    mount(h(Probe, { onHeight: (n) => (height = n) }))
    act(() => {
      vv.height = 480
      vv.offsetTop = 40
      vv.dispatchEvent(new Event('scroll'))
    })
    expect(height).toBe(280)
  })

  it('is 0 without visualViewport', () => {
    vi.stubGlobal('visualViewport', undefined)
    let height = -1
    mount(h(Probe, { onHeight: (n) => (height = n) }))
    expect(height).toBe(0)
  })

  it('drives the phone bar', async () => {
    const { container } = setup({ toolbar: { variant: 'phone' } })
    await settle()
    act(() => container.querySelector('.cm-content').focus())
    expect(container.querySelector('[data-variant=phone]')).toBeNull()
    act(() => {
      vv.height = 500
      vv.dispatchEvent(new Event('resize'))
    })
    expect(container.querySelector('[data-variant=phone]').style.bottom).toBe('300px')
  })
})

it('every file in the lane is ORM-free and app-agnostic: only the editor, CodeMirror and React are imported', async () => {
  const { readdirSync, readFileSync } = await import('node:fs')
  const { join } = await import('node:path')
  const dir = join(import.meta.dirname, '../src/preview')
  for (const name of readdirSync(dir)) {
    const text = readFileSync(join(dir, name), 'utf8')
    for (const m of text.matchAll(/from '([^']+)'/g)) {
      expect(m[1], `${name} imports ${m[1]}`).toMatch(/^(\.\/|\.\.\/editor\/|@codemirror\/|@lezer\/|react$)/)
    }
    expect(text, name).not.toMatch(/className=["'][^"']*\b(flex|px-|py-|text-|bg-)/)
  }
})
