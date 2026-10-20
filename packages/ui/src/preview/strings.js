// Copy for the live-preview layer, the editor toolbar and the mode toggle, verbatim from the EditorDesk /
// EditorPhone artboards (K§8). Hosts override any entry through the `strings` prop.

export const PREVIEW_STRINGS = {
  // Mode toggle (EditorDesk).
  modeGroup: 'Editor mode',
  livePreview: 'Live preview',
  source: 'Source',

  // Toolbar. The desk bar shows 'Link [[' and 'Image' as words; the phone bar uses the aria-labels below.
  formatting: 'Formatting',
  heading: 'Heading',
  bold: 'Bold',
  italic: 'Italic',
  bulletedList: 'Bulleted list',
  list: 'List',
  link: 'Link [[',
  insertLink: 'Insert link',
  image: 'Image',
  addImage: 'Add image',
  addImageOff: 'Add image, unavailable: attachments are off',
  imageOff: 'Image, unavailable: attachments are off',
  hideKeyboard: 'Hide keyboard',

  // An inline image the host could not resolve (or whose signed URL expired and did not come back).
  imageMissing: 'image not found',
}

/** The default strings with any host overrides laid over them. */
export function mergePreviewStrings(overrides) {
  return overrides ? { ...PREVIEW_STRINGS, ...overrides } : PREVIEW_STRINGS
}
