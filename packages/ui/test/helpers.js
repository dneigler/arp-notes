// Shared test helpers: schema example fixtures and a tiny React DOM mount (jsdom environment).
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { act, createElement as h } from 'react'
import { createRoot } from 'react-dom/client'

// node:path rather than new URL(): under the jsdom environment the global URL is jsdom's.
const FIXTURES = join(dirname(fileURLToPath(import.meta.url)), 'fixtures')

export function example(name) {
  return JSON.parse(readFileSync(join(FIXTURES, 'schema-examples', `${name}.json`), 'utf8'))
}

export function fixtureText(name) {
  return readFileSync(join(FIXTURES, name), 'utf8')
}

globalThis.IS_REACT_ACT_ENVIRONMENT = true

const mounted = []

/** Renders `element` into a fresh container and returns it. Call `cleanup()` in afterEach. */
export function mount(element) {
  const container = document.createElement('div')
  document.body.append(container)
  const root = createRoot(container)
  act(() => root.render(element))
  mounted.push({ root, container })
  return container
}

export function cleanup() {
  while (mounted.length) {
    const { root, container } = mounted.pop()
    act(() => root.unmount())
    container.remove()
  }
}

export { act, h }
