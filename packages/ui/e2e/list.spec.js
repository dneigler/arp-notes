import { expect, test } from '@playwright/test'
import { THEMES, axeViolations, openScene } from './helpers.js'

// C6b: every list/detail scene, including the overlays this lane owns (delete confirm, Kind and Source
// menus), is axe-clean (color-contrast included) in light, dark and both system themes.
const SCENES = [
  'list-desk',
  'list-phone',
  'list-auto',
  'list-empty',
  'list-menu-kind',
  'list-menu-source',
  'note-desk',
  'note-phone',
  'note-deleted',
  'note-deleted-desk',
  'note-delete-confirm',
  'note-auto',
  'note-written',
  'note-claude',
  'day-desk',
  'day-phone',
  'today-desk',
  'today-phone',
  'feed',
]

for (const theme of THEMES) {
  for (const scene of SCENES) {
    test(`${scene} is axe-clean in ${theme.name}`, async ({ page }) => {
      await openScene(page, scene, theme)
      expect(await axeViolations(page)).toEqual([])
    })
  }
}

test('the overlays are really open when axe looks at them', async ({ page }) => {
  await openScene(page, 'list-menu-kind', THEMES[0])
  await expect(page.getByRole('listbox', { name: 'Kind' })).toBeVisible()
  await openScene(page, 'list-menu-source', THEMES[0])
  await expect(page.getByRole('listbox', { name: 'Source' })).toBeVisible()
  await openScene(page, 'note-delete-confirm', THEMES[0])
  await expect(page.getByRole('alertdialog', { name: 'Delete this note from PT?' })).toBeVisible()
})

test('axe also passes with the confirm open in dark, at a phone width', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await openScene(page, 'note-delete-confirm', THEMES[1])
  expect(await axeViolations(page)).toEqual([])
})

test('the delete confirm traps Tab and returns focus on Escape', async ({ page }) => {
  await openScene(page, 'note-delete-confirm', THEMES[0])
  const dialog = page.getByRole('alertdialog')
  await expect(page.getByRole('button', { name: 'Cancel' })).toBeFocused()
  const inside = () => page.evaluate(() => !!document.activeElement?.closest('[role=alertdialog]'))
  for (let i = 0; i < 6; i += 1) {
    await page.keyboard.press('Tab')
    expect(await inside()).toBe(true)
  }
  await page.keyboard.press('Shift+Tab')
  expect(await inside()).toBe(true)
  await page.keyboard.press('Escape')
  await expect(dialog).toBeHidden()
  await expect(page.getByRole('button', { name: 'Delete from PT…' })).toBeFocused()
})

test('the phone Kind menu opens on click, closes on Escape and returns focus', async ({ page }) => {
  await openScene(page, 'list-phone', THEMES[0])
  const trigger = page.getByRole('button', { name: 'Kind' })
  await trigger.click()
  await expect(page.getByRole('listbox', { name: 'Kind' })).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(page.getByRole('listbox')).toBeHidden()
  await expect(trigger).toBeFocused()
})

// layout='auto' follows the component's own width (a host may embed it in a narrow column).
for (const viewport of [
  { width: 390, height: 844, layout: 'phone' },
  { width: 1280, height: 800, layout: 'desktop' },
]) {
  test(`the auto layout picks ${viewport.layout} at ${viewport.width}px and the page never scrolls sideways`, async ({ page }) => {
    await page.setViewportSize({ width: viewport.width, height: viewport.height })
    await openScene(page, 'list-auto', THEMES[0])
    await expect(page.locator('[data-notes-list]')).toHaveAttribute('data-layout', viewport.layout)
    await openScene(page, 'note-auto', THEMES[0])
    await expect(page.locator('[data-note-header]')).toHaveAttribute('data-layout', viewport.layout)
    for (const scene of ['list-auto', 'note-auto']) {
      await openScene(page, scene, THEMES[0])
      expect(await page.evaluate(() => document.documentElement.scrollWidth), scene).toBeLessThanOrEqual(viewport.width)
    }
  })
}

test('the auto layout re-measures when the window is resized', async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 800 })
  await openScene(page, 'list-auto', THEMES[0])
  await expect(page.locator('[data-notes-list]')).toHaveAttribute('data-layout', 'desktop')
  await page.setViewportSize({ width: 390, height: 844 })
  await expect(page.locator('[data-notes-list]')).toHaveAttribute('data-layout', 'phone')
})

test('chips and rows fit in the 390px phone list', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await openScene(page, 'list-phone', THEMES[0])
  const overflow = await page.evaluate(() => {
    const limit = document.documentElement.clientWidth
    return [...document.querySelectorAll('[data-notes-list] *')]
      .filter((el) => el.getBoundingClientRect().right > limit + 1)
      .map((el) => el.tagName)
  })
  expect(overflow).toEqual([])
})
