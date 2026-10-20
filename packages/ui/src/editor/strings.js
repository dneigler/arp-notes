// Copy for NoteEditor, NoteMetaFields and EditorRail, verbatim from the EditorDesk / EditorPhone
// artboards (K§8). Hosts override any entry through the `strings` prop; entries that carry numbers or
// names are functions.

export const EDITOR_STRINGS = {
  // [[ autocomplete popover.
  linkTo: (q) => `Link to · “${q}”`,
  linkHint: '↑ ↓ choose · Enter links · Esc keeps the text',
  // Row tag by entity_type; an unlisted type is shown capitalised.
  entityTypes: { repertoire: 'Piece', piece: 'Piece', work: 'Piece', movement: 'Movement', composer: 'Composer' },
  completionsLabel: 'Link suggestions',

  // Chips. The suffix after the label of a chip the host could not resolve (same words as NoteBody).
  notFound: 'not found',

  // Upload progress (in the editor and in the rail).
  uploading: (name) => `Uploading ${name}…`,
  keepTyping: 'Keep typing — the image appears when it lands',
  uploadFailed: (name) => `Couldn’t upload ${name}`,
  dismiss: 'Dismiss',

  // Policy dialog.
  imageNotAdded: 'Image not added',
  fileNotAdded: 'File not added',
  policyOff: 'This app doesn’t accept attachments, so the pasted image was left out. Your text is unchanged.',
  policyType: (name, allows) =>
    `${name} isn’t a type this app accepts${allows ? ` (it allows ${allows})` : ''}, so it was left out. Your text is unchanged.`,
  policySize: (name, size, limit) =>
    `${name} is ${size}, and this app accepts up to ${limit}, so it was left out. Your text is unchanged.`,
  ok: 'OK',

  // Autosave status line.
  saveStates: {
    idle: '',
    dirty: 'Unsaved changes',
    saving: 'Saving…',
    saved: 'Saved',
    conflict: 'Edited somewhere else — not saved',
    error: 'Couldn’t save — will retry',
  },

  // NoteMetaFields.
  title: 'Title',
  kind: 'Kind',
  date: 'Date',
  kindLabel: (kind) => (kind ? kind.charAt(0).toUpperCase() + kind.slice(1) : ''),

  // EditorRail.
  railTitle: 'In this note',
  links: 'Links',
  images: 'Images',
  noLinks: 'No links yet. Type [[ to link something.',
  noImages: 'No images yet. Paste or drop one.',
  chipNotFound: 'not found',
  uploadingShort: 'uploading',
  // Policy footer, rendered from GET /notes/capabilities (K§2); never hard-coded.
  policyAllows: (what, limit) => `This app allows ${what}${limit ? ` up to ${limit}` : ''}`,
  policyNone: 'This app doesn’t accept attachments',
  exportOn: 'export to Markdown on',
  exportOff: 'export to Markdown off',
  mimeNames: { 'image/*': 'Images', 'application/pdf': 'PDFs' },
  anyFile: 'Files',
}

/** The default strings with any host overrides laid over them (nested tables merge entry by entry). */
export function mergeStrings(overrides) {
  if (!overrides) return EDITOR_STRINGS
  return {
    ...EDITOR_STRINGS,
    ...overrides,
    entityTypes: { ...EDITOR_STRINGS.entityTypes, ...overrides.entityTypes },
    saveStates: { ...EDITOR_STRINGS.saveStates, ...overrides.saveStates },
    mimeNames: { ...EDITOR_STRINGS.mimeNames, ...overrides.mimeNames },
  }
}
