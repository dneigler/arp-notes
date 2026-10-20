import { expect, test } from '@playwright/test'
import { THEMES, axeViolations, openScene } from './helpers.js'

// C6c: the review open at the three widths K§8 names, in every theme, axe color-contrast included.
const VIEWPORTS = [
  { width: 390, height: 844, presentation: 'sheet' },
  { width: 820, height: 1180, presentation: 'formsheet' },
  { width: 1280, height: 800, presentation: 'dialog' },
]
const SCENES = ['review-auto', 'review-states']

for (const viewport of VIEWPORTS) {
  for (const theme of THEMES) {
    for (const scene of SCENES) {
      test(`${scene} at ${viewport.width}px (${viewport.presentation}) is axe-clean in ${theme.name}`, async ({ page }) => {
        await page.setViewportSize({ width: viewport.width, height: viewport.height })
        await openScene(page, scene, theme)
        const root = page.locator('[data-arpn="proposal-review"]')
        await expect(root).toHaveAttribute('data-presentation', viewport.presentation)
        expect(await axeViolations(page)).toEqual([])
      })
    }
  }
}

for (const viewport of VIEWPORTS) {
  test(`the ${viewport.presentation} fits a ${viewport.width}px screen and keeps its footer on screen`, async ({ page }) => {
    await page.setViewportSize({ width: viewport.width, height: viewport.height })
    await openScene(page, 'review-auto', THEMES[0])
    const dialog = page.getByRole('dialog', { name: 'Review links and actions' })
    const box = await dialog.boundingBox()
    expect(box.x).toBeGreaterThanOrEqual(0)
    expect(box.x + box.width).toBeLessThanOrEqual(viewport.width)
    expect(box.y + box.height).toBeLessThanOrEqual(viewport.height)
    await expect(page.getByRole('button', { name: /^Confirm \d+$/ })).toBeInViewport()
    await expect(page.getByRole('button', { name: 'Decide later' })).toBeInViewport()
    const scrollWidth = await page.evaluate(() => document.documentElement.scrollWidth)
    expect(scrollWidth).toBeLessThanOrEqual(viewport.width)
  })
}

test('Tab and Shift+Tab never leave the dialog', async ({ page }) => {
  await openScene(page, 'review-auto', THEMES[0])
  const inside = () => page.evaluate(() => !!document.activeElement?.closest('[role=dialog]'))
  for (let i = 0; i < 80; i += 1) {
    await page.keyboard.press('Tab')
    expect(await inside()).toBe(true)
  }
  for (let i = 0; i < 20; i += 1) {
    await page.keyboard.press('Shift+Tab')
    expect(await inside()).toBe(true)
  }
})

test('the sheet scrolls its list while the buttons stay put', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 600 })
  await openScene(page, 'review-auto', THEMES[0])
  const confirm = page.getByRole('button', { name: /^Confirm \d+$/ })
  const before = await confirm.boundingBox()
  await page.locator('[data-body]').evaluate((el) => {
    el.scrollTop = el.scrollHeight
  })
  const after = await confirm.boundingBox()
  expect(after.y).toBe(before.y)
  await expect(page.getByText('Action items').first()).toBeVisible()
})
