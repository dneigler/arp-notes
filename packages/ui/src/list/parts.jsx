// Pieces shared by NotesList, NoteCard and NoteDetailHeader: origin classification, badges, chips.
import { LockIcon } from './icons.jsx'
import { relativeTime, systemLabel } from './format.js'
import { styles } from './styles.js'

/** 'source' (imported file), 'llm' (written by a connected assistant) or 'app' (written here). */
export function originKind(note) {
  if (note?.source_system === 'llm') return 'llm'
  return note?.origin === 'source' ? 'source' : 'app'
}

/** Origin badge copy: 'Imported · Obsidian' (lock), 'Written here', 'Claude · via MCP'. */
export function OriginBadge({ note, strings, short = false, readOnly = false }) {
  const kind = originKind(note)
  if (kind === 'llm') {
    return (
      <span style={styles.badge('neu')} data-origin="llm">
        {short ? strings.claudeMcpShort : strings.claudeMcp}
      </span>
    )
  }
  if (kind === 'app') {
    return (
      <span style={styles.badge('app')} data-origin="app">
        {strings.writtenHere}
      </span>
    )
  }
  const system = systemLabel(note.source_system) || 'source'
  const text = readOnly
    ? short
      ? strings.readOnlyShort(system)
      : strings.importedReadOnly(system)
    : short
      ? strings.importedFromShort(system)
      : strings.importedFrom(system)
  return (
    <span style={styles.badge('imp')} data-origin="source">
      <LockIcon size={12} />
      {text}
    </span>
  )
}

/** 'N to review' (or an interactive button when onReview is given). */
export function ReviewBadge({ note, strings, onReview, text, href }) {
  const n = note?.review_pending ?? 0
  if (!(n > 0)) return null
  const label = text ?? strings.toReview(n)
  if (href && !onReview) {
    return (
      <a href={href} style={{ ...styles.badge('amb'), minHeight: 28, boxSizing: 'border-box' }} data-review-badge="">
        {label}
      </a>
    )
  }
  if (onReview) {
    return (
      <button type="button" style={{ ...styles.badge('amb'), cursor: 'pointer', minHeight: 28 }} onClick={() => onReview(note)} data-review-badge="">
        {label}
      </button>
    )
  }
  return (
    <span style={styles.badge('amb')} data-review-badge="">
      {label}
    </span>
  )
}

/** The relative-time phrase that fits the origin: Synced (imported), Edited (written here), Created (Claude). */
export function activityLabel(note, strings, now) {
  const kind = originKind(note)
  if (kind === 'source') {
    const ago = relativeTime(note.last_synced_at ?? note.updated_at, now)
    return ago ? strings.synced(ago) : ''
  }
  if (kind === 'llm') {
    const ago = relativeTime(note.created_at ?? note.updated_at, now)
    return ago ? strings.created(ago) : ''
  }
  const ago = relativeTime(note.updated_at, now)
  return ago ? strings.edited(ago) : ''
}

/** A link chip: an anchor when the host can route the entity, otherwise the same chip as plain text. */
export function EntityChip({ entityType, entityId, label, hrefForEntity, children }) {
  const href = hrefForEntity ? hrefForEntity(entityType, entityId) : null
  const content = children ?? label
  if (!href) {
    return (
      <span style={styles.chip} data-entity-type={entityType} data-entity-id={String(entityId)}>
        {content}
      </span>
    )
  }
  return (
    <a href={href} style={styles.chip} data-entity-type={entityType} data-entity-id={String(entityId)}>
      {content}
    </a>
  )
}
