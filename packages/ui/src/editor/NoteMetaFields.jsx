// NoteMetaFields: Title / Kind / Date above the editor (EditorDesk, EditorPhone). Controlled and
// fetch-free: each edit calls onChange with just the field that changed, which is the PATCH /notes/{id} body.
import { useId } from 'react'
import { mergeStrings } from './strings.js'
import { styles as s } from './styles.js'

/**
 * @param {object} props
 * @param {string} props.title
 * @param {string} props.kind
 * @param {string|null} [props.note_date]  'YYYY-MM-DD' or null.
 * @param {string[]} props.kinds  capabilities.kinds.
 * @param {(patch: {title?: string, kind?: string, note_date?: string|null}) => void} props.onChange
 * @param {boolean} [props.disabled]
 * @param {object} [props.strings]
 */
export function NoteMetaFields({ title = '', kind = '', note_date = null, kinds = [], onChange, disabled = false, strings: overrides }) {
  const strings = mergeStrings(overrides)
  const uid = useId()
  // A note whose kind this host no longer lists still shows its own kind rather than another one.
  const options = kind && !kinds.includes(kind) ? [kind, ...kinds] : kinds

  return (
    <div style={s.meta} data-arpn="note-meta">
      <div style={s.field}>
        <label htmlFor={`${uid}-title`} style={s.label}>
          {strings.title}
        </label>
        <input
          id={`${uid}-title`}
          type="text"
          style={{ ...s.input, ...s.titleInput }}
          value={title}
          disabled={disabled}
          onChange={(e) => onChange?.({ title: e.target.value })}
        />
      </div>
      <div style={s.metaRow}>
        <div style={s.field}>
          <label htmlFor={`${uid}-kind`} style={s.label}>
            {strings.kind}
          </label>
          <select
            id={`${uid}-kind`}
            style={s.input}
            value={kind}
            disabled={disabled}
            onChange={(e) => onChange?.({ kind: e.target.value })}
          >
            {options.map((k) => (
              <option key={k} value={k}>
                {strings.kindLabel(k)}
              </option>
            ))}
          </select>
        </div>
        <div style={s.field}>
          <label htmlFor={`${uid}-date`} style={s.label}>
            {strings.date}
          </label>
          <input
            id={`${uid}-date`}
            type="date"
            style={s.input}
            value={note_date ?? ''}
            disabled={disabled}
            onChange={(e) => onChange?.({ note_date: e.target.value || null })}
          />
        </div>
      </div>
    </div>
  )
}
