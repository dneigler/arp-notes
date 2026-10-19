import { expect, test } from '@playwright/test'
import { THEMES, axeViolations, openScene, sceneIds } from './helpers.js'

for (const theme of THEMES) {
  test(`every demo scene passes axe in ${theme.name}`, async ({ page }) => {
    const ids = await sceneIds(page)
    expect(ids.length).toBeGreaterThan(0)
    const failures = {}
    for (const id of ids) {
      await openScene(page, id, theme)
      const violations = await axeViolations(page)
      if (violations.length) failures[id] = violations
    }
    expect(failures).toEqual({})
  })
}

test('the harness discovers the C0 tokens scene', async ({ page }) => {
  expect(await sceneIds(page)).toContain('tokens')
})

test('pinned themes win over the system theme', async ({ page }) => {
  await openScene(page, 'tokens', { ...THEMES[0], colorScheme: 'dark' })
  const bg = await page.evaluate(() =>
    getComputedStyle(document.documentElement).getPropertyValue('--arpn-bg').trim(),
  )
  expect(bg.toLowerCase()).toBe('#ffffff')
})
