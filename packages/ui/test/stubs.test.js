import { describe, expect, it } from 'vitest'
import * as ui from '../src/index.js'

// K§7: every UI area stub is exported from src/index.js and throws until its lane lands.
// api/ and body/ have landed (C6a ga-mxal.13); they have their own tests.
const EXPORTS = {
  list: ['NotesList', 'NoteCard', 'NoteDetailHeader', 'NoteRail'],
  review: ['ProposalReview'],
  editor: ['NoteEditor', 'NoteMetaFields', 'EditorRail'],
  preview: ['livePreview', 'EditorToolbar', 'ModeToggle'],
}

describe('src/index.js re-exports every area stub', () => {
  for (const [area, names] of Object.entries(EXPORTS)) {
    it.each(names)(`${area}: %s is exported and not implemented`, (name) => {
      expect(typeof ui[name]).toBe('function')
      expect(() => ui[name]()).toThrow(/not implemented/)
    })
  }

  it('imports each area index.js on its own', async () => {
    for (const area of Object.keys(EXPORTS)) {
      const mod = await import(`../src/${area}/index.js`)
      expect(Object.keys(mod).sort()).toEqual([...EXPORTS[area]].sort())
    }
  })
})
