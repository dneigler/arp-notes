// Styles for the live-preview layer, as one CodeMirror theme: --arpn-* variables only (K§8). Heading sizes
// come from line decorations, so they work whatever the Markdown inside the line looks like. Source mode
// never loads any of this.
import { EditorView } from '@codemirror/view'

const v = (name) => `var(--arpn-${name})`

export const previewTheme = EditorView.theme({
  // Heading lines sized by level. The source-mode heading spans (C6d) size themselves too, so inside a
  // preview heading they take the line's size instead of multiplying it.
  '.arpn-lp-h1': { fontSize: '1.6em', fontWeight: '700', lineHeight: '1.3' },
  '.arpn-lp-h2': { fontSize: '1.35em', fontWeight: '700', lineHeight: '1.35' },
  '.arpn-lp-h3': { fontSize: '1.15em', fontWeight: '700', lineHeight: '1.4' },
  '.arpn-lp-h4, .arpn-lp-h5, .arpn-lp-h6': { fontWeight: '700' },
  '.arpn-lp-h1 .arpn-md-h, .arpn-lp-h2 .arpn-md-h, .arpn-lp-h3 .arpn-md-h': { fontSize: '1em' },

  // Markers: dimmed away from the cursor, the text colour on the cursor line (and on every selected line).
  '.arpn-lp-mark': { color: v('marker') },
  '.arpn-lp-active': { backgroundColor: v('actline') },
  '.arpn-lp-active .arpn-md-mark, .arpn-lp-active .arpn-lp-mark': { color: 'inherit' },

  // Inline images.
  '.arpn-lp-image': {
    display: 'inline-block',
    maxWidth: '100%',
    verticalAlign: 'middle',
    lineHeight: '0',
    cursor: 'pointer',
  },
  '.arpn-lp-image img': {
    display: 'block',
    maxWidth: '100%',
    height: 'auto',
    borderRadius: '8px',
    border: `1px solid ${v('border')}`,
  },
  '.arpn-lp-image[data-state="pending"]': {
    width: 'min(320px, 100%)',
    height: '120px',
    borderRadius: '8px',
    border: `1px solid ${v('border')}`,
    backgroundColor: v('shot'),
    backgroundImage: `repeating-linear-gradient(135deg, ${v('shot-line')} 0 2px, transparent 2px 12px)`,
  },
  '.arpn-lp-image[data-state="missing"]': {
    padding: '0 8px',
    borderRadius: '8px',
    border: `1px solid ${v('amb-fg')}`,
    background: v('amb-bg'),
    color: v('amb-fg'),
    fontSize: '0.92em',
    fontWeight: '600',
    lineHeight: '1.5',
  },
})
