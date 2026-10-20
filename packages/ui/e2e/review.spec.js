// C6c: ProposalReview in a real browser. axe (color-contrast included) in light and dark with the
// review open at 390, 820 and 1280 px, plus the keyboard, focus and emitted-body paths that need
// real focus handling. (The default demo.axe.spec.js already covers every scene in four themes.)
import { expect, test } from '@playwright/test'
import { AXE_TAGS, THEMES, axeViolations, openScene } from './helpers.js'

const WIDTHS = [
  { width: 390, height: 844, presentation: 'sheet' },
  { width: 820, height: 1180, presentation: 'formsheet' },
  { width: 1280, height: 900, presentation: 'dialog' },
]
const LIGHT_DARK = THEMES.filter((t) => ['light', 'dark'].includes(t.name))

const events = (page) => page.evaluate(() => window.__ARPN_REVIEW__.events)
const dialog = (page) => page.getByRole('dialog', { name: 'Review links and actions' })

for (const size of WIDTHS) {
  for (const theme of LIGHT_DARK) {
    test(`axe clean with the review open at ${size.width}px (${size.presentation}), ${theme.name}`, async ({ page }) => {
      await page.setViewportSize({ width: size.width, height: size.height })
      await openScene(page, 'review-auto', theme)
      await expect(page.locator('.arpn-rv')).toHaveAttribute('data-presentation', size.presentation)
      expect(await axeViolations(page)).toEqual([])

      // Every state of the sheet: sections expanded, a row rejected, the pick answered, an action flipped.
      for (const button of await page.getByRole('button', { name: /^Show \d+ more$/ }).all()) await button.click()
      await page.getByRole('button', { name: /^Reject link to Études, Op\.10 · Nº 3$/ }).click()
      await page.getByRole('radio', { name: /Préludes \(Book 1\)/ }).first().check()
      await page.getByRole('button', { name: 'Lesson' }).first().click()
      await page.getByRole('checkbox', { name: 'Save WTC Book 1 as someday' }).check()
      expect(await axeViolations(page)).toEqual([])
    })
  }
}

test('auto presentation follows the viewport when it is resized', async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 })
  await openScene(page, 'review-auto', THEMES[0])
  await expect(page.locator('.arpn-rv')).toHaveAttribute('data-presentation', 'dialog')
  await page.setViewportSize({ width: 820, height: 1180 })
  await expect(page.locator('.arpn-rv')).toHaveAttribute('data-presentation', 'formsheet')
  await page.setViewportSize({ width: 390, height: 844 })
  await expect(page.locator('.arpn-rv')).toHaveAttribute('data-presentation', 'sheet')
})

test.describe('keyboard and focus (dialog)', () => {
  test.beforeEach(async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 900 })
    await openScene(page, 'review-dialog', THEMES[0])
    await expect(dialog(page)).toBeFocused()
  })

  test('Tab stays inside the dialog and wraps both ways', async ({ page }) => {
    const inside = () => page.evaluate(() => !!document.activeElement.closest('[role=dialog]'))
    await page.keyboard.press('Tab')
    await expect(page.getByRole('button', { name: 'Close' })).toBeFocused()
    await page.keyboard.press('Shift+Tab') // before the first control: wraps to the last
    await expect(page.getByRole('button', { name: /^Confirm 17$/ })).toBeFocused()
    await page.keyboard.press('Tab') // after the last: wraps to the first
    await expect(page.getByRole('button', { name: 'Close' })).toBeFocused()
    for (let i = 0; i < 80; i += 1) {
      await page.keyboard.press('Tab')
      expect(await inside()).toBe(true)
    }
  })

  test('Esc is Decide later: one event, focus returns to the opener', async ({ page }) => {
    await page.keyboard.press('Escape')
    expect(await events(page)).toEqual([{ type: 'decideLater' }])
    await expect(page.locator('.arpn-rv')).toHaveCount(0)
    // Re-open from the opener, then close with Esc again: focus goes back to it.
    await page.locator('#open-review').focus()
    await page.keyboard.press('Enter')
    await expect(dialog(page)).toBeFocused()
    await page.keyboard.press('Escape')
    await expect(page.locator('#open-review')).toBeFocused()
  })

  test('Decide later and Close both call onDecideLater and nothing else', async ({ page }) => {
    await page.getByRole('button', { name: 'Decide later' }).click()
    await page.locator('#open-review').click()
    await page.getByRole('button', { name: 'Close' }).click()
    expect((await events(page)).map((e) => e.type)).toEqual(['decideLater', 'decideLater'])
  })

  test('a checkbox toggles with Space and the footer follows', async ({ page }) => {
    const box = page.getByRole('checkbox', { name: 'Link to Études, Op.10 · Nº 3' })
    await box.focus()
    await page.keyboard.press('Space')
    await expect(box).not.toBeChecked()
    await expect(page.getByText('Creates 13 links · 3 backlog items.')).toBeVisible()
    await expect(page.getByRole('button', { name: 'Confirm 16' })).toBeVisible()
  })

  test('reject keeps focus on the same button, which becomes Undo', async ({ page }) => {
    const reject = page.getByRole('button', { name: 'Reject link to Études, Op.10 · Nº 5' })
    await reject.focus()
    await page.keyboard.press('Enter')
    const undo = page.getByRole('button', { name: 'Undo reject of Études, Op.10 · Nº 5' })
    await expect(undo).toBeFocused()
    await expect(page.getByText('Rejected', { exact: true })).toBeVisible()
    await expect(page.getByRole('checkbox', { name: 'Link to Études, Op.10 · Nº 5, rejected' })).toBeDisabled()
    await page.keyboard.press('Enter')
    await expect(page.getByRole('checkbox', { name: 'Link to Études, Op.10 · Nº 5' })).toBeChecked()
    await expect(page.getByRole('button', { name: 'Reject link to Études, Op.10 · Nº 5' })).toBeFocused()
  })

  test('radios move with the arrow keys; skip is a choice, unpicked is not', async ({ page }) => {
    const group = page.getByRole('radiogroup')
    await expect(group.getByRole('radio', { checked: true })).toHaveCount(0)
    await page.getByRole('radio', { name: /Préludes, Livre 1/ }).focus()
    await page.keyboard.press('ArrowDown')
    await expect(page.getByRole('radio', { name: /Préludes \(Book 1\)/ }).first()).toBeChecked()
    await page.getByRole('radio', { name: 'None of these — skip' }).check()
    await expect(page.getByText('Debussy skipped.')).toBeVisible()
  })

  test('Confirm emits the ConfirmBody: defaults, with a reject, a pick and a lane change', async ({ page }) => {
    await page.getByRole('button', { name: 'Reject link to Études, Op.10 · Nº 3' }).click()
    await page.getByRole('radio', { name: /Preludes, Book 2/ }).check()
    await page.getByRole('button', { name: 'Lesson' }).first().click()
    await page.getByRole('checkbox', { name: 'Save Fauré as someday' }).check()
    await page.getByRole('button', { name: /^Confirm \d+$/ }).click()
    const event = (await events(page)).find((e) => e.type === 'confirm')
    expect(event).toBeDefined()
    const body = event.payload
    expect(Object.keys(body)).toEqual(['links', 'rejected', 'action_items', 'deferred', 'someday'])
    expect(body.rejected).toEqual([{ entity_type: 'movement', entity_id: 1003, anchor: 'op-10-no-3' }])
    expect(body.deferred).toEqual([])
    expect(body.links).toHaveLength(14) // 13 ticked + the picked Debussy book
    expect(body.links.find((l) => l.anchor === 'debussy')).toMatchObject({ entity_id: 20 })
    expect(body.action_items[0]).toMatchObject({ lane: 'lesson', text: 'Practice Nº 12 slowly — drop the hand' })
    expect(body.action_items[0].link_index).toBeGreaterThanOrEqual(0)
    expect(body.someday).toEqual([expect.objectContaining({ mention: 'Fauré', kind_hint: 'composer' })])
  })

  test('an unpicked ambiguous item is deferred on Confirm', async ({ page }) => {
    await page.getByRole('button', { name: /^Confirm 17$/ }).click()
    const [event] = await events(page)
    expect(event.payload.deferred).toEqual([{ mention: 'Debussy', anchor: 'debussy' }])
    expect(event.payload.someday).toEqual([])
  })

  test('Reject all emits every target as rejected, with no links', async ({ page }) => {
    await page.getByRole('button', { name: 'Reject all' }).click()
    const [event] = await events(page)
    expect(event.type).toBe('rejectAll')
    expect(event.payload.links).toEqual([])
    expect(event.payload.rejected).toHaveLength(16 + 4)
  })

  test('Show more and Untick all', async ({ page }) => {
    await page.getByRole('button', { name: 'Show 6 more' }).click()
    await expect(page.getByRole('checkbox', { name: /^Link to / })).toHaveCount(11 + 3 + 2)
    await page.getByRole('button', { name: 'Untick all in Pieces · high' }).click()
    await expect(page.getByText('Creates 3 links · 3 backlog items.')).toBeVisible()
    await page.getByRole('button', { name: 'Tick all in Pieces · high' }).click()
    await expect(page.getByText('Creates 14 links · 3 backlog items.')).toBeVisible()
  })
})

test('Someday switches show only when onSomeday is given', async ({ page }) => {
  await page.setViewportSize({ width: 820, height: 1180 })
  await openScene(page, 'review-formsheet', THEMES[0]) // no onSomeday
  await expect(dialog(page)).toBeVisible()
  await expect(page.getByText('WTC Book 1', { exact: true })).toBeVisible()
  await expect(page.getByRole('checkbox', { name: /as someday/ })).toHaveCount(0)
  await expect(page.getByText('Someday', { exact: true })).toHaveCount(0)

  await openScene(page, 'review-dialog', THEMES[0]) // with onSomeday
  await page.getByRole('checkbox', { name: 'Save WTC Book 1 as someday' }).check()
  expect((await events(page)).at(-1)).toEqual({ type: 'someday', payload: { mention: expect.objectContaining({ mention: 'WTC Book 1' }), enabled: true } })
})

test('the phone sheet keeps every control reachable and the footer on screen', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await openScene(page, 'review-sheet', THEMES[0])
  const confirm = page.getByRole('button', { name: /^Confirm 17$/ })
  await expect(confirm).toBeInViewport()
  const box = await confirm.boundingBox()
  expect(box.height).toBeGreaterThanOrEqual(44)
  // No horizontal overflow of the sheet at 390 px.
  const overflow = await page.evaluate(() => {
    const d = document.querySelector('.arpn-rv__dialog')
    return d.scrollWidth - d.clientWidth
  })
  expect(overflow).toBeLessThanOrEqual(0)
})

test('axe tag set is the C0 harness set', () => {
  expect(AXE_TAGS).toContain('wcag2aa')
})
