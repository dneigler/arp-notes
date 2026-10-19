// C0 scene: every text/background pairing the package relies on, so axe checks the real palette
// in light and dark. Foreground tokens always sit on their intended background token.
const PAIRS = [
  ['fg', 'bg'],
  ['fg', 'card'],
  ['fg', 'raised'],
  ['fg', 'sel'],
  ['fg2', 'surface'],
  ['muted', 'bg'],
  ['muted', 'surface'],
  ['accent', 'bg'],
  ['on-accent', 'accent-fill'],
  ['on-primary', 'primary'],
  ['chip-fg', 'chip-bg'],
  ['imp-fg', 'imp-bg'],
  ['app-fg', 'app-bg'],
  ['amb-fg', 'amb-bg'],
  ['neu-fg', 'neu-bg'],
  ['del-fg', 'del-bg'],
]

export default {
  id: 'tokens',
  title: 'Tokens',
  render(container) {
    const heading = document.createElement('h1')
    heading.textContent = 'Design tokens'
    const grid = document.createElement('div')
    grid.style.cssText = 'display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:12px'
    for (const [fg, bg] of PAIRS) {
      const cell = document.createElement('div')
      cell.style.cssText = `padding:12px 16px;border-radius:10px;border:1px solid var(--arpn-border);background:var(--arpn-${bg});color:var(--arpn-${fg})`
      cell.textContent = `${fg} on ${bg}`
      grid.append(cell)
    }
    container.append(heading, grid)
  },
}
