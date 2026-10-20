import { expect, test } from '@playwright/test'
import { THEMES, axeViolations, openScene } from './helpers.js'

// C6d: the editor at the three widths K§8 names, in every theme, axe color-contrast included, on every
// route and with every overlay of this bead open (the [[ popover, the 'Image not added' dialog).
const VIEWPORTS = [
  { width: 390, height: 844 },
  { width: 820, height: 1180 },
  { width: 1280, height: 800 },
]

// Each scene, and what to wait for before it counts as "open".
const SCENES = [
  { id: 'editor-desk', ready: (page) => expect(page.locator('.arpn-chip[data-state=found]').first()).toBeVisible() },
  { id: 'editor-autocomplete', ready: (page) => expect(page.locator('.cm-tooltip-autocomplete .cm-completionLabel').first()).toBeVisible() },
  { id: 'editor-policy-off', ready: (page) => expect(page.getByRole('dialog', { name: 'Image not added' })).toBeVisible() },
  { id: 'editor-uploading', ready: (page) => expect(page.getByRole('progressbar')).toHaveCount(1) },
]

for (const viewport of VIEWPORTS) {
  for (const theme of THEMES) {
    for (const scene of SCENES) {
      test(`${scene.id} at ${viewport.width}px is axe-clean in ${theme.name}`, async ({ page }) => {
        await page.setViewportSize({ width: viewport.width, height: viewport.height })
        await openScene(page, scene.id, theme)
        await scene.ready(page)
        expect(await axeViolations(page)).toEqual([])
      })
    }
  }
}

for (const viewport of VIEWPORTS) {
  for (const scene of SCENES) {
    test(`${scene.id} fits a ${viewport.width}px screen without sideways scroll`, async ({ page }) => {
      await page.setViewportSize({ width: viewport.width, height: viewport.height })
      await openScene(page, scene.id, THEMES[0])
      await scene.ready(page)
      expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(viewport.width)
      const tip = page.locator('.cm-tooltip-autocomplete')
      if (await tip.count()) {
        const box = await tip.boundingBox()
        expect(box.x).toBeGreaterThanOrEqual(0)
        expect(box.x + box.width).toBeLessThanOrEqual(viewport.width)
      }
    })
  }
}

const editor = (page) => page.getByRole('textbox', { name: 'Note body' })

test('the desk draws resolved chips, a not-found chip, and the rail agrees', async ({ page }) => {
  await openScene(page, 'editor-desk', THEMES[0])
  await expect(page.locator('.arpn-chip[data-state=found]')).toHaveCount(3)
  const missing = page.locator('.arpn-chip[data-state=missing]')
  await expect(missing).toHaveText('@Lost piece · not found')
  const rail = page.getByRole('complementary', { name: 'In this note' })
  await expect(rail.getByRole('heading', { name: 'Links · 4' })).toBeVisible()
  await expect(rail.getByRole('heading', { name: 'Images · 1' })).toBeVisible()
  await expect(rail.locator('[data-link="ex://repertoire/404"]')).toContainText('not found')
  await expect(page.locator('[data-arpn=policy-footer]')).toHaveText('This app allows Images and PDFs up to 25 MB · export to Markdown on')
})

test('a pending chip is dashed, not dimmed, so it stays axe-clean while it resolves', async ({ page }) => {
  for (const theme of THEMES) {
    await openScene(page, 'editor-desk', theme)
    await expect(page.locator('.arpn-chip[data-state=found]').first()).toBeVisible()
    // Chips resolve in a tick, so draw a pending one by hand instead of racing the resolver. It goes under
    // .cm-editor (the theme's scope) but outside .cm-content, which CodeMirror would repaint.
    await page.evaluate(() => {
      const chip = document.createElement('span')
      chip.className = 'arpn-chip'
      chip.dataset.state = 'pending'
      chip.dataset.probe = 'pending'
      chip.textContent = '@Still resolving'
      document.querySelector('.cm-editor').append(chip)
    })
    const style = await page.locator('[data-probe=pending]').evaluate((el) => {
      const cs = getComputedStyle(el)
      return { opacity: cs.opacity, borderStyle: cs.borderTopStyle }
    })
    expect(style).toEqual({ opacity: '1', borderStyle: 'dashed' })
    expect(await axeViolations(page)).toEqual([])
    await page.locator('[data-probe=pending]').evaluate((el) => el.remove())
  }
})

test('typing [[ opens the popover; Enter links the chosen row', async ({ page }) => {
  await openScene(page, 'editor-desk', THEMES[0])
  await editor(page).click()
  await page.keyboard.press('ControlOrMeta+End')
  await page.keyboard.type('\nSee [[chop')
  const tip = page.locator('.cm-tooltip-autocomplete')
  await expect(tip.locator('.arpn-wiki-head')).toHaveText('Link to · “chop”')
  await expect(tip.locator('.arpn-wiki-hint')).toHaveText('↑ ↓ choose · Enter links · Esc keeps the text')
  await expect(tip.getByRole('option')).toHaveCount(1)
  await expect(tip.getByRole('option').first()).toContainText('Chopin')
  await expect(tip.getByRole('option').first()).toContainText('Composer')
  // CodeMirror ignores Enter for 75 ms after a popover appears, so a fast typist's newline is not eaten.
  await page.waitForTimeout(150)
  await page.keyboard.press('Enter')
  await expect(tip).toHaveCount(0)
  // The chip is drawn; the Markdown underneath is the house form.
  await expect(page.locator('.arpn-chip', { hasText: '@Chopin' })).toHaveCount(2)
  const text = await page.evaluate(() => document.querySelector('.cm-content').innerText)
  expect(text).not.toContain('[[chop')
})

test('arrow keys choose a row, and the typed rows carry their kind', async ({ page }) => {
  await openScene(page, 'editor-desk', THEMES[0])
  await editor(page).click()
  await page.keyboard.press('ControlOrMeta+End')
  await page.keyboard.type('\n[[etu')
  const options = page.locator('.cm-tooltip-autocomplete').getByRole('option')
  await expect(options).toHaveCount(4)
  await expect(options.nth(0)).toHaveAttribute('aria-selected', 'true')
  await expect(options.nth(0)).toContainText('Piece')
  await expect(options.nth(1)).toContainText('Movement')
  await page.waitForTimeout(150) // CodeMirror's interaction delay (75 ms) after a popover appears
  await page.keyboard.press('ArrowDown')
  await expect(options.nth(1)).toHaveAttribute('aria-selected', 'true')
})

test('Esc closes the popover and keeps the typed text', async ({ page }) => {
  await openScene(page, 'editor-desk', THEMES[0])
  await editor(page).click()
  await page.keyboard.press('ControlOrMeta+End')
  await page.keyboard.type('\n[[etu')
  await expect(page.locator('.cm-tooltip-autocomplete')).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(page.locator('.cm-tooltip-autocomplete')).toHaveCount(0)
  expect(await page.evaluate(() => document.querySelector('.cm-content').innerText)).toContain('[[etu')
})

test('clicking a chip shows its source; moving away draws it again', async ({ page }) => {
  await openScene(page, 'editor-desk', THEMES[0])
  const chip = page.locator('.arpn-chip', { hasText: '@Chopin' })
  await expect(chip).toBeVisible()
  await chip.click()
  await expect(page.locator('.arpn-chip', { hasText: '@Chopin' })).toHaveCount(0)
  expect(await page.evaluate(() => document.querySelector('.cm-content').innerText)).toContain('[@Chopin](ex://composer/13)')
  await page.keyboard.press('ControlOrMeta+Home')
  await expect(page.locator('.arpn-chip', { hasText: '@Chopin' })).toHaveCount(1)
})

test('the policy dialog explains, traps focus, and OK returns to the text', async ({ page }) => {
  await openScene(page, 'editor-policy-off', THEMES[0])
  const dialog = page.getByRole('dialog', { name: 'Image not added' })
  await expect(dialog).toContainText('This app doesn’t accept attachments, so the pasted image was left out. Your text is unchanged.')
  const ok = dialog.getByRole('button', { name: 'OK' })
  await expect(ok).toBeFocused()
  await page.keyboard.press('Tab')
  await expect(ok).toBeFocused()
  await ok.click()
  await expect(dialog).toHaveCount(0)
  await expect(page.locator('[data-arpn=policy-footer]')).toHaveText('This app doesn’t accept attachments · export to Markdown on')
})

test('an upload in flight shows its progress in the editor and the rail, and keeps the placeholder in the text', async ({ page }) => {
  await openScene(page, 'editor-uploading', THEMES[0])
  const strip = page.locator('[data-upload=uploading]')
  await expect(strip).toContainText('Uploading IMG_2041.png…')
  await expect(strip).toContainText('62% · 1.8 of 2.9 MB')
  await expect(strip).toContainText('Keep typing — the image appears when it lands')
  await expect(page.getByRole('progressbar')).toHaveAttribute('aria-valuenow', '62')
  await expect(page.locator('[data-image=uploading]')).toContainText('IMG_2041.png')
  await expect(page.locator('[data-image=uploading]')).toContainText('62%')
  expect(await page.evaluate(() => document.querySelector('.cm-content').innerText)).toContain('![uploading IMG_2041.png…](attachment://pending-')
})

test('the active line is drawn with the actline token', async ({ page }) => {
  await openScene(page, 'editor-desk', THEMES[0])
  await editor(page).click()
  const bg = await page.locator('.cm-activeLine').first().evaluate((el) => getComputedStyle(el).backgroundColor)
  expect(bg).toBe('rgb(248, 250, 252)')
  await openScene(page, 'editor-desk', THEMES[1])
  await editor(page).click()
  expect(await page.locator('.cm-activeLine').first().evaluate((el) => getComputedStyle(el).backgroundColor)).toBe('rgb(31, 31, 35)')
})

test.describe('touch (emulated iPad, 820 px)', () => {
  test.use({ viewport: { width: 820, height: 1180 }, hasTouch: true, isMobile: true })

  test('a tap focuses the editor and a tap on a popover row inserts the chip', async ({ page }) => {
    await openScene(page, 'editor-desk', THEMES[0])
    await editor(page).tap()
    await page.keyboard.press('ControlOrMeta+End')
    await page.keyboard.type('\n[[bach')
    const row = page.locator('.cm-tooltip-autocomplete').getByRole('option').first()
    await expect(row).toContainText('Bach')
    await row.tap()
    await expect(page.locator('.arpn-chip', { hasText: '@Bach' })).toHaveCount(1)
  })
})
