import { describe, expect, it } from 'vitest'
import { drift } from '../scripts/vendor-schemas.mjs'
import { schemaNames } from '../src/api/index.js'
import { example } from './helpers.js'
import { assertShape } from '../src/api/index.js'

describe('vendored core schemas', () => {
  it('are byte-identical to packages/core (run: npm run schemas:vendor)', () => {
    expect(drift()).toEqual([])
  })

  it('accept every core example for their model', () => {
    const names = schemaNames()
    expect(names.length).toBeGreaterThan(40)
    for (const name of names) assertShape(name, example(name))
  })
})
