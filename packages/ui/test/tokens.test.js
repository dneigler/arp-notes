import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

// Contract K§8 plus the five names K§12.5 adds (37 in all). A name added to or removed from
// tokens.css needs a contract bead first.
const K8_NAMES = (
  'bg surface card raised fg fg2 muted marker border border2 accent accent-fill on-accent primary ' +
  'on-primary chip-bg chip-fg chip-bd imp-bg imp-fg app-bg app-fg amb-bg amb-fg neu-bg neu-fg ' +
  'del-bg del-fg scrim shot sel shadow shot-line well grab tile actline'
).split(' ')

const css = readFileSync(new URL('../src/styles/tokens.css', import.meta.url), 'utf8').replace(
  /\/\*[\s\S]*?\*\//g,
  '',
)

// Body of the first `selector { ... }` at or after `from`, with nested braces balanced.
function blockAfter(selector, from = 0) {
  const start = css.indexOf(selector, from)
  if (start < 0) throw new Error(`selector not found: ${selector}`)
  const open = css.indexOf('{', start)
  let depth = 0
  for (let i = open; i < css.length; i++) {
    if (css[i] === '{') depth++
    if (css[i] === '}' && --depth === 0) return { body: css.slice(open + 1, i), end: i }
  }
  throw new Error(`unbalanced braces after ${selector}`)
}

function declarations(body) {
  const out = {}
  for (const m of body.matchAll(/--arpn-([a-z0-9-]+)\s*:\s*([^;]+);/g)) out[m[1]] = m[2].trim()
  return out
}

const light = declarations(blockAfter(':root {').body)
const dark = declarations(blockAfter(':root[data-theme="dark"]').body)
const media = blockAfter('@media (prefers-color-scheme: dark)')
const system = declarations(blockAfter(':root:not([data-theme="light"])', css.indexOf('@media')).body)

describe('tokens.css (K§8, K§12.5)', () => {
  it('declares 37 names', () => {
    expect(K8_NAMES).toHaveLength(37)
  })

  it.each([
    ['light (:root)', light],
    ['dark ([data-theme="dark"])', dark],
    ['dark (prefers-color-scheme: dark)', system],
  ])('declares every K§8 name, and only those, in %s', (_label, vars) => {
    expect(Object.keys(vars).sort()).toEqual([...K8_NAMES].sort())
  })

  it('uses the same dark values for the pinned and the system dark theme', () => {
    expect(system).toEqual(dark)
  })

  it('gives dark its own value for every token except the two the mockups share', () => {
    const same = K8_NAMES.filter((n) => light[n] === dark[n])
    // These are identical in both themes in the approved mockups.
    expect(same.sort()).toEqual(['accent-fill', 'on-accent'])
  })

  it('wraps the system dark block in the prefers-color-scheme media query', () => {
    expect(media.body).toContain(':root:not([data-theme="light"])')
  })
})
