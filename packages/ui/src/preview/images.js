// Inline image widgets for the live-preview layer. The host turns an attachment reference into a URL
// (`resolveAttachment`); the widget draws it in place of the Markdown and puts the Markdown back, for
// editing, as soon as the cursor goes inside it. The document is never touched.
import { WidgetType } from '@codemirror/view'

/**
 * One answer per image text, asked of the host once and then kept: a widget rebuilt later paints at once
 * instead of flashing the placeholder again. `clear()` forgets everything (signed URLs were refreshed).
 * @param {(ref: object) => string|null|undefined|Promise<string|null|undefined>} resolve
 */
export function createImageCache(resolve) {
  const entries = new Map()
  return {
    entry(image) {
      let entry = entries.get(image.text)
      if (!entry) {
        entry = { value: null, promise: null }
        entry.promise = Promise.resolve()
          .then(() => resolve(image))
          .then(
            (url) => (typeof url === 'string' && url ? { url } : { missing: true }),
            () => {
              entries.delete(image.text) // a host error is not an answer: ask again next time
              return { missing: true }
            },
          )
          .then((value) => (entry.value = value))
        entries.set(image.text, entry)
      }
      return entry
    },
    /** The image failed to load (an expired signed URL): forget its URL so the next redraw asks again. */
    expire(image) {
      const entry = entries.get(image.text)
      if (entry) entry.value = { missing: true }
      entries.delete(image.text)
    },
    clear() {
      entries.clear()
    },
  }
}

class ImageWidget extends WidgetType {
  constructor(image, entry, { cache, strings, onExpired }) {
    super()
    this.image = image
    this.entry = entry
    this.cache = cache
    this.strings = strings
    this.onExpired = onExpired
  }

  eq(other) {
    return other.image.text === this.image.text && other.entry === this.entry && other.entry.value === this.entry.value
  }

  paint(dom) {
    const { image } = this
    const value = this.entry.value
    dom.replaceChildren()
    if (!value) {
      dom.dataset.state = 'pending'
      dom.setAttribute('aria-hidden', 'true')
      return
    }
    if (value.missing) {
      dom.dataset.state = 'missing'
      dom.removeAttribute('aria-hidden')
      dom.textContent = `${image.alt || image.target} · ${this.strings.imageMissing}`
      return
    }
    dom.dataset.state = 'found'
    dom.removeAttribute('aria-hidden')
    const img = document.createElement('img')
    img.src = value.url
    img.alt = image.alt || image.target
    img.loading = 'lazy'
    img.decoding = 'async'
    if (image.width) img.width = image.width
    if (image.height) img.height = image.height
    img.addEventListener('error', () => {
      this.cache.expire(image)
      this.entry.value = { missing: true }
      this.paint(dom)
      this.onExpired?.(image)
    })
    dom.append(img)
  }

  toDOM(view) {
    const dom = document.createElement('span')
    dom.className = 'arpn-lp-image'
    dom.dataset.kind = this.image.kind
    this.paint(dom)
    if (!this.entry.value) this.entry.promise.then(() => this.paint(dom))
    // A click puts the cursor inside the Markdown, which shows its source for editing.
    dom.addEventListener('mousedown', (event) => {
      event.preventDefault()
      const from = view.posAtDOM(dom)
      view.dispatch({ selection: { anchor: Math.min(from + 2, from + this.image.text.length - 1) } })
      view.focus()
    })
    return dom
  }

  ignoreEvent() {
    return true
  }
}

/**
 * A function from an image found in the document to its widget.
 * @param {ReturnType<typeof createImageCache>} cache
 * @param {{strings: object, onExpired?: (image: object) => void}} context
 */
export function imageWidgetFactory(cache, context) {
  return (image) => new ImageWidget(image, cache.entry(image), { cache, ...context })
}
