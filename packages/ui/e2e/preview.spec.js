import { expect, test } from '@playwright/test'
import { THEMES, axeViolations, openScene } from './helpers.js'

// C6e: the live-preview layer, toolbar and mode toggle at the three widths K§8 names, in every theme, axe
// color-contrast included, on every route and with every overlay of this bead open (the [[ popover the
// toolbar's Link button opens; the dimmed Image button of an app that takes no attachments).
const VIEWPORTS = [
  { width: 390, height: 844 },
  { width: 820, height: 1180 },
  { width: 1280, height: 800 },
]

const SCENES = [
  { id: 'preview-desk', ready: (page) => expect(page.locator('.arpn-lp-image img')).toHaveCount(2) },
  { id: 'preview-source', ready: (page) => expect(page.locator('.cm-content')).toContainText('# Roy Howat masterclass') },
  { id: 'preview-phone', ready: (page) => expect(page.locator('[data-variant=phone]')).toBeVisible() },
  { id: 'preview-link-popover', ready: (page) => expect(page.locator('.cm-tooltip-autocomplete .cm-completionLabel').first()).toBeVisible() },
  { id: 'preview-images-off', ready: (page) => expect(page.getByRole('button', { name: 'Image, unavailable: attachments are off' })).toBeVisible() },
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
const sizeOf = (locator) => locator.evaluate((el) => parseFloat(getComputedStyle(el).fontSize))

test('headings are sized by level, markers dim off the cursor line and read normally on it', async ({ page }) => {
  await openScene(page, 'preview-desk', THEMES[0])
  const h1 = page.locator('.cm-line.arpn-lp-h1')
  const h2 = page.locator('.cm-line.arpn-lp-h2')
  const h3 = page.locator('.cm-line.arpn-lp-h3')
  const body = page.locator('.cm-line', { hasText: 'Slow practice' })
  expect(await sizeOf(h1)).toBeGreaterThan(await sizeOf(h2))
  expect(await sizeOf(h2)).toBeGreaterThan(await sizeOf(h3))
  expect(await sizeOf(h3)).toBeGreaterThan(await sizeOf(body))

  const colorOf = (locator) => locator.evaluate((el) => getComputedStyle(el).color)
  const marker = await page.evaluate(() => {
    const probe = document.createElement('span')
    probe.style.color = 'var(--arpn-marker)'
    document.body.append(probe)
    const color = getComputedStyle(probe).color
    probe.remove()
    return color
  })
  // The caret starts on the **bold** line: its asterisks are the text colour; the list dashes are dimmed.
  await expect(page.locator('.cm-line.arpn-lp-active')).toContainText('**the weight on the first beat**')
  const boldLine = page.locator('.cm-line', { hasText: 'the weight on the first beat' })
  const asterisk = boldLine.locator('.arpn-md-mark').first()
  expect(await colorOf(asterisk)).not.toBe(marker)
  expect(await colorOf(page.locator('.cm-line', { hasText: 'Slow practice' }).locator('.arpn-lp-mark').first())).toBe(marker)

  // Moving the caret moves the reveal.
  await body.click()
  await expect(page.locator('.cm-line.arpn-lp-active')).toContainText('Slow practice')
  expect(await colorOf(boldLine.locator('.arpn-lp-mark').first())).toBe(marker)
})

test('images are drawn in place of their Markdown, and the caret inside one brings the Markdown back', async ({ page }) => {
  await openScene(page, 'preview-desk', THEMES[0])
  await expect(page.locator('.arpn-lp-image img')).toHaveCount(2)
  await expect(editor(page)).not.toContainText('attachment://41')
  const first = page.locator('.arpn-lp-image').first()
  const box = await first.boundingBox()
  expect(box.width).toBeGreaterThan(100)
  await first.click()
  await expect(editor(page)).toContainText('![IMG_2040.png](attachment://41)')
  await expect(page.locator('.arpn-lp-image img')).toHaveCount(1)
})

test('the Source toggle removes the preview and keeps the document; Live preview brings it back', async ({ page }) => {
  await openScene(page, 'preview-desk', THEMES[0])
  const toggle = page.getByRole('group', { name: 'Editor mode' })
  await expect(toggle.getByRole('button', { name: 'Live preview' })).toHaveAttribute('aria-pressed', 'true')
  const before = await editor(page).evaluate((el) => el.innerText)
  await toggle.getByRole('button', { name: 'Source' }).click()
  await expect(toggle.getByRole('button', { name: 'Source' })).toHaveAttribute('aria-pressed', 'true')
  await expect(page.locator('[class*="arpn-lp-"]:not([data-arpn])')).toHaveCount(0)
  await expect(page.locator('.cm-line.arpn-lp-h1')).toHaveCount(0)
  await expect(editor(page)).toContainText('![IMG_2040.png](attachment://41)')
  await toggle.getByRole('button', { name: 'Live preview' }).click()
  await expect(page.locator('.cm-line.arpn-lp-h1')).toHaveCount(1)
  // innerText differs only where widgets stand in for Markdown; the headings' text is the same.
  expect(await editor(page).evaluate((el) => el.innerText)).toContain('# Roy Howat masterclass')
  expect(before).toContain('# Roy Howat masterclass')
})

test('the toolbar writes Markdown: Heading, Bold, Italic, list, Link [[', async ({ page }) => {
  await openScene(page, 'preview-source', THEMES[0])
  await editor(page).click()
  await page.keyboard.press('ControlOrMeta+End')
  await page.keyboard.type('\nnew line')
  const toolbar = page.getByRole('toolbar', { name: 'Formatting' })
  await toolbar.getByRole('button', { name: 'Heading' }).click()
  await expect(page.locator('.cm-line', { hasText: 'new line' })).toHaveText('## new line')
  await toolbar.getByRole('button', { name: 'Heading' }).click()
  await expect(page.locator('.cm-line', { hasText: 'new line' })).toHaveText('new line')
  await toolbar.getByRole('button', { name: 'Bulleted list' }).click()
  await expect(page.locator('.cm-line', { hasText: 'new line' })).toHaveText('- new line')
  // Focus never left the editor, so typing goes straight on.
  await page.keyboard.type('!')
  await expect(page.locator('.cm-line', { hasText: 'new line' })).toHaveText('- new line!')
  await toolbar.getByRole('button', { name: 'Bold' }).click()
  await expect(page.locator('.cm-line', { hasText: 'new line' })).toContainText('**')
  await toolbar.getByRole('button', { name: 'Link [[' }).click()
  await expect(page.locator('.cm-tooltip-autocomplete .arpn-wiki-head')).toBeVisible()
})

test('every toolbar and toggle target is at least 44 px', async ({ page }) => {
  for (const id of ['preview-desk', 'preview-phone']) {
    await page.setViewportSize({ width: 390, height: 844 })
    await openScene(page, id, THEMES[0])
    const sizes = await page.locator('[data-arpn=editor-toolbar] button, [data-arpn=mode-toggle] button').evaluateAll((els) =>
      els.map((el) => ({ name: el.getAttribute('aria-label') || el.textContent, w: el.getBoundingClientRect().width, h: el.getBoundingClientRect().height })),
    )
    expect(sizes.length).toBeGreaterThanOrEqual(7)
    for (const s of sizes) {
      expect(s.w, s.name).toBeGreaterThanOrEqual(44)
      expect(s.h, s.name).toBeGreaterThanOrEqual(44)
    }
  }
})

test('the phone bar sits on the keyboard’s top edge and Hide keyboard is there', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await openScene(page, 'preview-phone', THEMES[0])
  const bar = page.locator('[data-variant=phone]')
  const box = await bar.boundingBox()
  // A simulated 320 px keyboard: the bar's bottom edge is 320 px above the screen's bottom.
  expect(Math.round(844 - (box.y + box.height))).toBe(320)
  expect(box.width).toBe(390)
  await expect(bar.getByRole('button', { name: 'Hide keyboard' })).toBeVisible()
  for (const name of ['Heading', 'Bold', 'Italic', 'List', 'Insert link', 'Add image']) {
    await expect(bar.getByRole('button', { name })).toBeVisible()
  }
})

test('with attachments off the Image button is dimmed and opens no file chooser', async ({ page }) => {
  await openScene(page, 'preview-images-off', THEMES[0])
  const image = page.getByRole('button', { name: 'Image, unavailable: attachments are off' })
  await expect(image).toHaveAttribute('aria-disabled', 'true')
  let chooser = false
  page.on('filechooser', () => (chooser = true))
  await image.click({ force: true })
  await page.waitForTimeout(150)
  expect(chooser).toBe(false)
})

test('Image opens the file chooser', async ({ page }) => {
  await openScene(page, 'preview-desk', THEMES[0])
  const [chooser] = await Promise.all([page.waitForEvent('filechooser'), page.getByRole('button', { name: 'Image' }).click()])
  expect(chooser.isMultiple()).toBe(true)
})
