// Pure formatting helpers for the list and detail chrome. No DOM, no React: easy to test, and the
// same strings come out on the server and in the browser.

const MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December']
const WEEKDAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']

/** Source systems the contract names (capabilities.source_systems) and how they read in the UI. */
export const SYSTEM_LABELS = {
  obsidian: 'Obsidian',
  notion: 'Notion',
  apple_notes: 'Apple Notes',
  llm: 'Claude',
}

export function systemLabel(system) {
  if (!system) return ''
  if (SYSTEM_LABELS[system]) return SYSTEM_LABELS[system]
  return system.charAt(0).toUpperCase() + system.slice(1).replace(/_/g, ' ')
}

/** 'masterclass' -> 'Masterclass'. */
export function kindLabel(kind) {
  if (!kind) return ''
  return kind.charAt(0).toUpperCase() + kind.slice(1).replace(/_/g, ' ')
}

/** Parses 'YYYY-MM-DD' (a calendar date, no zone) into UTC parts, or null. */
function dateParts(value) {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(value ?? '')
  return m ? { y: Number(m[1]), m: Number(m[2]) - 1, d: Number(m[3]) } : null
}

/**
 * Parses a wire timestamp to epoch ms. The wire carries naive ISO strings ('2026-10-18T14:30:00');
 * they are read as UTC, the same as the server writes them. Returns NaN when it does not parse.
 */
export function parseTimestamp(value) {
  if (value == null || value === '') return NaN
  const text = String(value)
  const hasZone = /(?:Z|[+-]\d{2}:?\d{2})$/i.test(text)
  return Date.parse(/T|\s\d/.test(text) && !hasZone ? `${text.replace(' ', 'T')}Z` : text)
}

/** 'Sun 18 Oct 2026' from a calendar date (note_date). Never shifts by the viewer's zone. */
export function formatNoteDate(value) {
  const p = dateParts(value)
  if (!p) return ''
  const weekday = WEEKDAYS[new Date(Date.UTC(p.y, p.m, p.d)).getUTCDay()]
  return `${weekday} ${p.d} ${MONTHS[p.m].slice(0, 3)} ${p.y}`
}

/** '18 Oct' from a timestamp or date. */
export function formatDayMonth(value, timeZone) {
  const ms = parseTimestamp(value)
  if (Number.isNaN(ms)) {
    const p = dateParts(value)
    return p ? `${p.d} ${MONTHS[p.m].slice(0, 3)}` : ''
  }
  const parts = new Intl.DateTimeFormat('en-GB', { day: 'numeric', month: 'short', timeZone }).formatToParts(ms)
  const get = (t) => parts.find((x) => x.type === t)?.value ?? ''
  return `${get('day')} ${get('month')}`
}

/** '11:05' (24 h) in `timeZone` (default: the viewer's). */
export function formatClock(value, timeZone) {
  const ms = parseTimestamp(value)
  if (Number.isNaN(ms)) return ''
  return new Intl.DateTimeFormat('en-GB', { hour: '2-digit', minute: '2-digit', hour12: false, timeZone }).format(ms)
}

/** The month a note belongs to in the list: its note_date, else the day it last changed. */
export function monthKey(summary) {
  const p = dateParts(summary.note_date) ?? dateParts(summary.updated_at)
  return p ? `${p.y}-${String(p.m + 1).padStart(2, '0')}` : 'undated'
}

/** 'October 2026' for a month key. */
export function monthTitle(key) {
  const m = /^(\d{4})-(\d{2})$/.exec(key)
  return m ? `${MONTHS[Number(m[2]) - 1]} ${m[1]}` : 'Undated'
}

function plural(n, one, many = `${one}s`) {
  return `${n} ${n === 1 ? one : many}`
}

export { plural }

/** '2 days ago', '1 hour ago', 'just now'. `now` is epoch ms (a prop in the components, for tests). */
export function relativeTime(value, now = Date.now()) {
  const ms = parseTimestamp(value)
  if (Number.isNaN(ms)) return ''
  const seconds = Math.max(0, Math.round((now - ms) / 1000))
  if (seconds < 60) return 'just now'
  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) return `${plural(minutes, 'minute')} ago`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${plural(hours, 'hour')} ago`
  const days = Math.floor(hours / 24)
  if (days < 14) return `${plural(days, 'day')} ago`
  if (days < 60) return `${plural(Math.floor(days / 7), 'week')} ago`
  if (days < 365) return `${plural(Math.floor(days / 30), 'month')} ago`
  return `${plural(Math.floor(days / 365), 'year')} ago`
}

/** Directory part of a source path with a trailing slash, or null at the vault root. */
export function sourceFolder(path) {
  if (!path) return null
  const i = path.lastIndexOf('/')
  return i > 0 ? `${path.slice(0, i)}/` : null
}

export function formatBytes(bytes) {
  const n = Number(bytes) || 0
  if (n >= 1024 * 1024) return `${(n / (1024 * 1024)).toFixed(2)} MB`
  if (n >= 1024) return `${Math.round(n / 1024)} KB`
  return `${n} B`
}

/** frontmatter.duration when it is a whole number of minutes, else null (K§2 duration_min). */
export function durationMinutes(note) {
  if (Number.isInteger(note?.duration_min)) return note.duration_min
  const raw = note?.frontmatter?.duration
  if (raw == null) return null
  const text = String(raw).trim()
  return /^\d+$/.test(text) ? Number(text) : null
}

/** Whether a source_url is safe to put in an href (no script schemes). */
export function safeHref(url) {
  if (typeof url !== 'string') return null
  return /^\s*(?:javascript|vbscript|data):/i.test(url) ? null : url
}
