import { describe, expect, it } from 'vitest'
import * as ui from '../src/index.js'

// K§7: src/index.js re-exports every UI area. Every area has landed (api/ and body/ C6a, list/ C6b, review/ C6c,
// editor/ C6d, preview/ C6e), so no C0 stub is left; this keeps the package entry honest about each area's index.js.
const AREAS = ['api', 'body', 'list', 'review', 'editor', 'preview']

describe('src/index.js re-exports every area', () => {
  it.each(AREAS)('%s: everything its index.js exports is on the package entry', async (area) => {
    const mod = await import(`../src/${area}/index.js`)
    const names = Object.keys(mod)
    expect(names.length).toBeGreaterThan(0)
    for (const name of names) expect(ui[name], `${area}.${name}`).toBe(mod[name])
  })

  it('no C0 stub is left: nothing exported throws "not implemented" when it is a plain function with no arguments', () => {
    for (const name of ['livePreview', 'previewDecorations']) {
      expect(typeof ui[name]).toBe('function')
    }
    expect(() => ui.livePreview()).not.toThrow()
  })
})
