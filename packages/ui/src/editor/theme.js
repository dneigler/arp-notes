// CodeMirror theme: --arpn-* variables only (K§8), so the host's light, dark or system theme applies with
// nothing to import. Sizes follow the EditorDesk / EditorPhone artboards. The 16 px text size also keeps
// iOS from zooming the page when the editor is focused.
import { EditorView } from '@codemirror/view'

const v = (name) => `var(--arpn-${name})`
const MONO = 'ui-monospace, SFMono-Regular, Menlo, Consolas, monospace'

export const editorTheme = EditorView.theme({
  '&': {
    color: v('fg'),
    backgroundColor: v('bg'),
    fontSize: '16px',
    border: `1px solid ${v('border')}`,
    borderRadius: '12px',
    minHeight: 'var(--arpn-editor-min-height, 280px)',
  },
  '&.cm-focused': { outline: `2px solid ${v('accent')}`, outlineOffset: '1px' },
  '.cm-scroller': { fontFamily: 'inherit', lineHeight: '1.65', overflow: 'auto' },
  '.cm-content': { padding: '14px 0', caretColor: v('fg'), maxWidth: '100%' },
  '.cm-line': { padding: '0 16px' },
  '.cm-cursor, .cm-dropCursor': { borderLeftColor: v('fg') },
  '.cm-activeLine': { backgroundColor: v('actline') },
  '&.cm-focused > .cm-scroller > .cm-selectionLayer .cm-selectionBackground, .cm-selectionBackground, .cm-content ::selection': {
    backgroundColor: v('sel'),
  },

  // Source-mode Markdown.
  '.arpn-md-mark': { color: v('marker') },
  '.arpn-md-h': { fontWeight: '700' },
  '.arpn-md-h1': { fontSize: '1.25em' },
  '.arpn-md-h2': { fontSize: '1.125em' },
  '.arpn-md-strong': { fontWeight: '700' },
  '.arpn-md-em': { fontStyle: 'italic' },
  '.arpn-md-strike': { textDecoration: 'line-through' },
  '.arpn-md-code': { fontFamily: MONO, fontSize: '0.92em' },
  '.arpn-md-url': { color: v('accent') },
  '.arpn-md-quote': { color: v('fg2') },

  // Host link chips.
  '.arpn-chip': {
    display: 'inline-block',
    padding: '0 8px',
    margin: '0 1px',
    borderRadius: '999px',
    border: `1px solid ${v('chip-bd')}`,
    background: v('chip-bg'),
    color: v('chip-fg'),
    fontSize: '0.92em',
    fontWeight: '600',
    lineHeight: '1.5',
    cursor: 'pointer',
  },
  // Pending reads as dashed, not dimmed: opacity would blend chip-fg into chip-bg below 4.5:1.
  '.arpn-chip[data-state="pending"]': { borderStyle: 'dashed' },
  '.arpn-chip[data-state="missing"]': { background: v('amb-bg'), color: v('amb-fg'), borderColor: v('amb-fg') },

  // The [[ popover.
  '.cm-tooltip.cm-tooltip-autocomplete': {
    background: v('raised'),
    color: v('fg'),
    border: `1px solid ${v('border2')}`,
    borderRadius: '12px',
    boxShadow: v('shadow'),
    overflow: 'hidden',
    width: 'min(420px, calc(100vw - 32px))',
    maxWidth: 'calc(100vw - 32px)',
  },
  '.cm-tooltip.cm-tooltip-autocomplete > ul': {
    fontFamily: 'inherit',
    fontSize: '15px',
    maxHeight: '260px',
    maxWidth: 'none',
    minWidth: '0',
  },
  '.cm-tooltip.cm-tooltip-autocomplete > ul > li': {
    display: 'flex',
    alignItems: 'baseline',
    gap: '12px',
    padding: '10px 14px',
    minHeight: '24px',
    color: v('fg'),
    lineHeight: '1.3',
  },
  '.cm-tooltip.cm-tooltip-autocomplete > ul > li[aria-selected]': {
    background: v('sel'),
    color: v('fg'),
  },
  '.cm-tooltip.cm-tooltip-autocomplete .cm-completionLabel': { flex: '1 1 auto', minWidth: '0', fontWeight: '600' },
  '.cm-tooltip.cm-tooltip-autocomplete .cm-completionDetail': {
    flex: '0 0 auto',
    marginLeft: '0',
    fontStyle: 'normal',
    fontSize: '13px',
    color: v('muted'),
  },
  '.arpn-wiki-head': {
    padding: '10px 14px 8px',
    fontSize: '13px',
    fontWeight: '600',
    color: v('muted'),
    borderBottom: `1px solid ${v('border')}`,
  },
  '.arpn-wiki-hint': {
    padding: '8px 14px',
    fontSize: '12px',
    color: v('muted'),
    borderTop: `1px solid ${v('border')}`,
  },
})
