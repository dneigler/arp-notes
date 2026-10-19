import AxeBuilder from '@axe-core/playwright'

// Four ways a host can be themed: pinned light, pinned dark, and following the OS in either mode.
export const THEMES = [
  { name: 'light', query: '?theme=light', colorScheme: 'light' },
  { name: 'dark', query: '?theme=dark', colorScheme: 'dark' },
  { name: 'system-light', query: '', colorScheme: 'light' },
  { name: 'system-dark', query: '', colorScheme: 'dark' },
]

export const AXE_TAGS = ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']

export async function openScene(page, id, theme) {
  await page.emulateMedia({ colorScheme: theme.colorScheme })
  await page.goto(`/${theme.query}#/${id}`)
  await page.waitForFunction((sceneId) => window.__ARPN_DEMO__?.current === sceneId, id)
}

export async function sceneIds(page) {
  await page.goto('/')
  await page.waitForFunction(() => window.__ARPN_DEMO__ !== undefined)
  return page.evaluate(() => window.__ARPN_DEMO__.scenes)
}

// Returns the axe violations for the open scene (empty array = clean).
export async function axeViolations(page) {
  const { violations } = await new AxeBuilder({ page }).withTags(AXE_TAGS).analyze()
  return violations.map((v) => ({
    rule: v.id,
    impact: v.impact,
    nodes: v.nodes.map((n) => ({ target: n.target, summary: n.failureSummary })),
  }))
}
