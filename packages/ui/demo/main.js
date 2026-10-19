// Demo harness entry (C0). A "scene" is one renderable slice of the UI package. Every C6 bead adds
// demo/scenes/<area>.js with a default export { id, title, render(container) } (or an array of
// them); scenes are discovered with import.meta.glob, so no shared file is edited. The Playwright
// spec visits every scene in light, dark and both system themes and runs axe on each.
import '../src/styles/tokens.css'
import './demo.css'

const modules = import.meta.glob('./scenes/*.js', { eager: true })
const scenes = Object.values(modules)
  .flatMap((m) => [].concat(m.default ?? []))
  .sort((a, b) => a.id.localeCompare(b.id))

const params = new URLSearchParams(location.search)
const theme = params.get('theme') // 'light' | 'dark' | null (follow the system)
if (theme === 'light' || theme === 'dark') {
  document.documentElement.dataset.theme = theme
}

const nav = document.getElementById('demo-nav')
const stage = document.getElementById('demo-stage')
const state = (window.__ARPN_DEMO__ = { scenes: scenes.map((s) => s.id), current: null })

function renderNav(currentId) {
  nav.replaceChildren()
  const label = document.createElement('strong')
  label.textContent = 'arp-notes UI demo'
  nav.append(label)
  for (const scene of scenes) {
    const link = document.createElement('a')
    link.href = `${location.search}#/${scene.id}`
    link.textContent = scene.title
    if (scene.id === currentId) link.setAttribute('aria-current', 'page')
    nav.append(link)
  }
}

function render() {
  const id = location.hash.replace(/^#\//, '') || scenes[0]?.id
  const scene = scenes.find((s) => s.id === id)
  renderNav(scene?.id)
  stage.replaceChildren()
  if (!scene) {
    stage.textContent = `Unknown scene: ${id}`
  } else {
    scene.render(stage)
  }
  state.current = scene?.id ?? null
}

window.addEventListener('hashchange', render)
render()
