import { expect, test } from '@playwright/test'
import { THEMES, axeViolations, openScene } from './helpers.js'

for (const theme of THEMES) {
  test(`NoteBody overlays are axe-clean in ${theme.name}: source opened by a real click`, async ({ page }) => {
    await openScene(page, 'body', theme)
    const toggle = page.getByRole('button', { name: 'Show source' })
    await toggle.click()
    await expect(page.getByRole('button', { name: 'Hide source' })).toHaveAttribute('aria-expanded', 'true')
    await expect(page.locator('[data-dataview] pre')).toBeVisible()
    expect(await axeViolations(page)).toEqual([])
  })
}

test('the dataview toggle is keyboard operable and collapses again', async ({ page }) => {
  await openScene(page, 'body', THEMES[0])
  await page.getByRole('button', { name: 'Show source' }).focus()
  await page.keyboard.press('Enter')
  await expect(page.locator('[data-dataview] pre')).toBeVisible()
  await page.keyboard.press('Space')
  await expect(page.locator('[data-dataview] pre')).toBeHidden()
})

test('the phone column does not scroll sideways, even on the corpus', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 800 })
  for (const id of ['body-phone', 'body-corpus-open']) {
    await openScene(page, id, THEMES[0])
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)
    expect(overflow, id).toBeLessThanOrEqual(0)
  }
})

test('highlights, markers and chips render in the real browser', async ({ page }) => {
  await openScene(page, 'body', THEMES[0])
  await expect(page.locator('mark').first()).toHaveText('Keep the melody singing and the left hand quiet.')
  await expect(page.locator('[data-marker="backlog"]')).toHaveText('→ practice backlog')
  await expect(page.locator('[data-marker="pending"]')).toHaveText('needs a pick')
  await expect(page.locator('[data-chip="missing"]')).toHaveCount(1)
  await expect(page.locator('[data-chip="resolved"]').first()).toHaveAttribute('href', /entity=repertoire-35/)
  await expect(page.locator('img').first()).toBeVisible()
})

test('an image error with no onAttachmentExpired handler does not throw', async ({ page }) => {
  await openScene(page, 'body', THEMES[0])
  const errors = []
  page.on('pageerror', (e) => errors.push(e.message))
  await page.evaluate(() => document.querySelector('img').dispatchEvent(new Event('error')))
  expect(errors).toEqual([])
})
