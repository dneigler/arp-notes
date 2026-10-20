// NotesList: the /notes page body. Search and filters, the sync line, rows grouped by month, the
// empty state. It never fetches: items and sync sources come in as props, filter changes go out
// through onFiltersChange, and routes are the host's (hrefForNote).
import { useEffect, useId, useMemo, useRef, useState } from 'react'
import { ChevronDownIcon, DocIcon, PlusIcon, SyncIcon } from './icons.jsx'
import { durationMinutes, formatNoteDate, kindLabel, monthKey, monthTitle, relativeTime, sourceFolder, systemLabel } from './format.js'
import { useIsPhone } from './hooks.js'
import { OriginBadge, ReviewBadge, EntityChip, activityLabel, originKind } from './parts.jsx'
import { styles } from './styles.js'
import { withStrings } from './strings.js'

export const DEFAULT_KINDS = ['masterclass', 'workshop', 'lecture', 'reading', 'video', 'reflection', 'meeting', 'note']

/** The filter state NotesList edits. `source` is 'obsidian' | 'llm' | 'app' | '' (all). */
export const EMPTY_FILTERS = { q: '', origin: 'all', kind: '', source: '', includeDeleted: false }

/**
 * Maps NotesList filters onto GET /notes query params (K§2): "Practice Tracker" / "Written here" is
 * origin=app, never a source_system value. Empty values are left out.
 */
export function filtersToParams(filters) {
  const f = { ...EMPTY_FILTERS, ...filters }
  const params = {}
  if (f.q) params.q = f.q
  if (f.kind) params.kind = f.kind
  if (f.source === 'app') params.origin = 'app'
  else {
    if (f.origin === 'source' || f.origin === 'app') params.origin = f.origin
    if (f.source) params.source_system = f.source
  }
  if (f.includeDeleted) params.include_deleted = true
  return params
}

function filtersActive(f) {
  return Boolean(f.q || f.origin !== 'all' || f.kind || f.source || f.includeDeleted)
}

// Empty-tile heuristic: an imported file with nothing in it (no images, links or pending picks).
// Hosts that know better pass isEmpty.
function defaultIsEmpty(n) {
  return originKind(n) === 'source' && !n.thumbnail_url && !n.link_count && !n.attachment_count && !n.review_pending && !(n.top_links?.length)
}

function useOutsideClose(open, onClose, ref) {
  useEffect(() => {
    if (!open) return undefined
    const onDown = (e) => {
      if (ref.current && !ref.current.contains(e.target)) onClose()
    }
    document.addEventListener('mousedown', onDown)
    return () => document.removeEventListener('mousedown', onDown)
  }, [open, onClose, ref])
}

/** A button that opens a small listbox menu (phone filter chips). Esc closes and returns focus. */
function MenuChip({ label, value, options, onChange, strings, testId }) {
  const [open, setOpen] = useState(false)
  const wrap = useRef(null)
  const trigger = useRef(null)
  const menuId = useId()
  useOutsideClose(open, () => setOpen(false), wrap)
  const selected = options.find((o) => o.value === value)
  const on = value !== ''
  useEffect(() => {
    if (!open) return
    wrap.current?.querySelector('[role="option"][aria-selected="true"], [role="option"]')?.focus()
  }, [open])
  const choose = (v) => {
    setOpen(false)
    trigger.current?.focus()
    onChange(v)
  }
  const onKeyDown = (e) => {
    const items = [...(wrap.current?.querySelectorAll('[role="option"]') ?? [])]
    const i = items.indexOf(document.activeElement)
    if (e.key === 'Escape') {
      e.stopPropagation()
      setOpen(false)
      trigger.current?.focus()
    } else if (e.key === 'ArrowDown') {
      e.preventDefault()
      items[Math.min(items.length - 1, i + 1)]?.focus()
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      items[Math.max(0, i - 1)]?.focus()
    }
  }
  return (
    <span ref={wrap} style={{ position: 'relative', display: 'inline-flex' }} onKeyDown={open ? onKeyDown : undefined} data-menu={testId}>
      <button
        ref={trigger}
        type="button"
        style={styles.filterChip(on)}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={open ? menuId : undefined}
        onClick={() => setOpen((v) => !v)}
      >
        {on && selected ? selected.label : label}
        <ChevronDownIcon size={14} />
      </button>
      {open ? (
        <div id={menuId} role="listbox" aria-label={label} style={styles.menu}>
          {options.map((o) => (
            <button
              key={o.value || '__all'}
              type="button"
              role="option"
              aria-selected={o.value === value}
              style={styles.menuItem(o.value === value)}
              onClick={() => choose(o.value)}
            >
              {o.label}
            </button>
          ))}
        </div>
      ) : null}
    </span>
  )
}

function SyncLine({ sources, strings, now, phone }) {
  const rows = [...(sources ?? [])]
    .filter((s) => s && s.last_synced_at)
    .sort((a, b) => String(b.last_synced_at).localeCompare(String(a.last_synced_at)))
  if (!rows.length) return null
  return (
    <div style={{ ...styles.muted, fontSize: 13, display: 'flex', flexDirection: 'column', gap: 2, alignItems: phone ? 'flex-start' : 'flex-end' }} data-sync-line="">
      {rows.map((s) => (
        <span key={`${s.source_system}/${s.source_workspace}`} style={{ display: 'inline-flex', gap: 6, alignItems: 'center' }}>
          {phone ? null : <SyncIcon />}
          {strings.lastSync(systemLabel(s.source_system), s.source_workspace, relativeTime(s.last_synced_at, now))}
        </span>
      ))}
    </div>
  )
}

function Thumb({ note, strings, isEmpty, phone, onAttachmentExpired }) {
  if (phone) return null
  const box = { width: 72, height: 54, flex: 'none', borderRadius: 8, boxSizing: 'border-box' }
  if (note.thumbnail_url) {
    return <img src={note.thumbnail_url} alt="" loading="lazy" onError={onAttachmentExpired} style={{ ...styles.shot, ...box }} data-thumb="image" />
  }
  if (isEmpty(note)) {
    return (
      <div
        style={{ ...box, border: '1px dashed var(--arpn-border2)', display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--arpn-muted)', fontSize: 12 }}
        data-thumb="empty"
      >
        {strings.emptyTile}
      </div>
    )
  }
  return (
    <div style={{ ...box, background: 'var(--arpn-surface)', display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--arpn-muted)' }} data-thumb="doc" aria-hidden="true">
      <DocIcon size={22} />
    </div>
  )
}

function metaLine(note, strings, phone) {
  const parts = [kindLabel(note.kind)]
  if (note.person) parts.push(note.person)
  const date = formatNoteDate(note.note_date)
  if (date) parts.push(phone ? date.replace(/^\w{3} /, '').replace(/ \d{4}$/, '') : date)
  const minutes = durationMinutes(note)
  if (minutes != null && !phone) parts.push(strings.minutes(minutes))
  if (originKind(note) === 'source' && !phone) {
    parts.push(sourceFolder(note.source_path) ?? strings.vaultRoot)
  }
  return parts.filter(Boolean).join(' · ')
}

function Row({ note, strings, now, hrefForNote, isEmpty, phone, onAttachmentExpired }) {
  const top = note.top_links ?? []
  const shownChips = phone ? top.slice(0, 2) : top
  const extraLinks = Math.max(0, (note.link_count ?? 0) - shownChips.length)
  const counts = []
  if (extraLinks) counts.push(phone ? `+${extraLinks}` : strings.moreLinks(extraLinks))
  if (!phone && note.action_count) counts.push(strings.actions(note.action_count))
  if (note.attachment_count) counts.push(strings.images(note.attachment_count))
  const activity = activityLabel(note, strings, now)
  const deleted = Boolean(note.deleted_at)
  const href = hrefForNote ? hrefForNote(note.id) : undefined
  const origin = originKind(note)
  return (
    <li style={{ listStyle: 'none', borderTop: '1px solid var(--arpn-border)' }} data-note-id={note.id}>
      <a
        href={href}
        style={{ display: 'flex', gap: 16, alignItems: 'flex-start', padding: phone ? '14px 16px' : '16px 20px', color: 'inherit', textDecoration: 'none' }}
      >
        <Thumb note={note} strings={strings} isEmpty={isEmpty} phone={phone} onAttachmentExpired={onAttachmentExpired} />
        <div style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column', gap: phone ? 5 : 6 }}>
          <div style={{ display: 'flex', gap: phone ? 6 : 8, alignItems: 'center', flexWrap: 'wrap' }}>
            <span style={{ fontSize: 16, fontWeight: 600, flex: phone ? 1 : undefined, minWidth: 0, overflowWrap: 'anywhere' }}>{note.title}</span>
            {phone ? null : <OriginBadge note={note} strings={strings} />}
            {deleted ? <span style={styles.badge('del')}>{strings.rowSourceDeleted}</span> : null}
            <ReviewBadge note={note} strings={strings} />
          </div>
          {phone ? (
            <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
              <OriginBadge note={note} strings={strings} short />
              <span style={{ ...styles.muted, fontSize: 13 }}>{metaLine(note, strings, true)}</span>
            </div>
          ) : (
            <div style={{ ...styles.muted, fontSize: 13 }}>
              {metaLine(note, strings, false)}
              {origin === 'llm' ? ` · ${strings.llmProvenance}` : ''}
            </div>
          )}
          {shownChips.length || counts.length ? (
            <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center' }}>
              {shownChips.map((l) => (
                <span key={`${l.entity_type}/${l.entity_id}`} style={styles.chip}>
                  {l.entity_label}
                </span>
              ))}
              {counts.length ? <span style={{ ...styles.muted, fontSize: 13 }}>{counts.join(' · ')}</span> : null}
            </div>
          ) : null}
          {phone && activity ? <div style={{ ...styles.muted, fontSize: 12 }}>{activity}</div> : null}
        </div>
        {!phone && activity ? (
          <div style={{ ...styles.muted, fontSize: 13, textAlign: 'right', whiteSpace: 'nowrap' }} data-activity={origin}>
            {activity}
          </div>
        ) : null}
      </a>
    </li>
  )
}

function EmptyState({ strings, onNew, howSyncingHref, phone }) {
  return (
    <div style={{ padding: phone ? '40px 24px' : '56px 24px', display: 'flex', flexDirection: 'column', alignItems: 'center', textAlign: 'center', gap: 12 }} data-empty="">
      <div style={{ width: 64, height: 64, borderRadius: 999, background: 'var(--arpn-surface)', display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--arpn-muted)' }}>
        <DocIcon size={28} />
      </div>
      <h2 style={{ margin: 0, fontSize: 20, fontWeight: 700 }}>{strings.emptyTitle}</h2>
      <p style={{ ...styles.muted, margin: 0, fontSize: 15, maxWidth: 420 }}>{strings.emptyBody}</p>
      {onNew ? (
        <button type="button" style={{ ...styles.button, ...styles.buttonPrimary, width: '100%', maxWidth: 420, marginTop: 8 }} onClick={onNew}>
          {strings.emptyWrite}
        </button>
      ) : null}
      <div style={{ ...styles.card, width: '100%', maxWidth: 420, padding: 16, textAlign: 'left', display: 'flex', flexDirection: 'column', gap: 6, marginTop: 8 }}>
        <div style={{ fontWeight: 600 }}>{strings.emptySyncTitle}</div>
        <div style={{ ...styles.muted, fontSize: 14 }}>{strings.emptySyncBody}</div>
        {howSyncingHref ? (
          <a href={howSyncingHref} style={{ ...styles.link, fontSize: 14, fontWeight: 600, minHeight: 44, display: 'inline-flex', alignItems: 'center' }}>
            {strings.emptySyncLink}
          </a>
        ) : null}
      </div>
    </div>
  )
}

/**
 * @param {Object} props
 * @param {import('../api/types.js').NoteSummary[]} props.items
 * @param {import('../api/types.js').NoteList['sync_sources']} [props.syncSources]
 * @param {Partial<typeof EMPTY_FILTERS>} [props.filters]  Controlled filter state.
 * @param {(next: typeof EMPTY_FILTERS) => void} [props.onFiltersChange]  Map to a query with filtersToParams.
 * @param {() => void} [props.onNew]
 * @param {(id: number) => string|undefined} [props.hrefForNote]
 * @param {boolean} [props.loading]
 * @param {Error|string|null} [props.error]
 * @param {string[]} [props.kinds]  capabilities.kinds; defaults to the eight D8 kinds.
 * @param {string} [props.hostName]  Names the app in the Source menu ('Practice Tracker').
 * @param {string} [props.howSyncingHref]  Target of the empty state's 'How syncing works' link; omitted = no link.
 * @param {() => void} [props.onAttachmentExpired]  A thumbnail failed to load (its signed URL expired, K§8): re-fetch the list.
 * @param {() => void} [props.onLoadMore]  Renders a 'Load more' button after the last row.
 * @param {(note: import('../api/types.js').NoteSummary) => boolean} [props.isEmpty]  Decides the dashed 'Empty' tile.
 * @param {'auto'|'desktop'|'phone'} [props.layout]
 * @param {number} [props.now]  Epoch ms for relative times (tests).
 * @param {boolean} [props.showHeading]  Render the 'Notes' heading block (default true).
 * @param {Partial<import('./strings.js').STRINGS>} [props.strings]
 */
export function NotesList({
  items,
  syncSources,
  filters,
  onFiltersChange,
  onNew,
  hrefForNote,
  loading = false,
  error = null,
  kinds = DEFAULT_KINDS,
  hostName = 'Practice Tracker',
  howSyncingHref,
  onLoadMore,
  onAttachmentExpired,
  isEmpty = defaultIsEmpty,
  layout = 'auto',
  now,
  showHeading = true,
  strings: stringOverrides,
}) {
  const strings = useMemo(() => withStrings(stringOverrides), [stringOverrides])
  const f = { ...EMPTY_FILTERS, ...filters }
  const [ref, phone] = useIsPhone(layout)
  const clock = now ?? Date.now()
  const set = (patch) => onFiltersChange?.({ ...f, ...patch })
  const searchId = useId()

  const groups = useMemo(() => {
    const byMonth = new Map()
    for (const note of items ?? []) {
      const key = monthKey(note)
      if (!byMonth.has(key)) byMonth.set(key, [])
      byMonth.get(key).push(note)
    }
    return [...byMonth.entries()]
  }, [items])

  const kindOptions = [{ value: '', label: strings.allKinds }, ...kinds.map((k) => ({ value: k, label: kindLabel(k) }))]
  const sourceOptions = [
    { value: '', label: strings.allSources },
    { value: 'obsidian', label: strings.sourceObsidian },
    { value: 'llm', label: strings.sourceLlm },
    { value: 'app', label: hostName },
  ]
  const originOptions = [
    ['all', strings.originAll],
    ['source', strings.originSource],
    ['app', strings.originApp],
  ]
  const errorText = error ? (typeof error === 'string' ? error : error.message) : ''
  const active = filtersActive(f)
  const hasItems = (items?.length ?? 0) > 0

  const filtersDesktop = (
    <form aria-label={strings.filterLabel} style={{ display: 'flex', flexWrap: 'wrap', gap: 12, alignItems: 'flex-end' }} onSubmit={(e) => e.preventDefault()}>
      <label style={{ ...styles.fieldLabel, flex: '1 1 260px' }} htmlFor={searchId}>
        {strings.search}
        <input id={searchId} type="search" style={styles.input} placeholder={strings.searchPlaceholder} value={f.q} onChange={(e) => set({ q: e.target.value })} />
      </label>
      <div style={styles.fieldLabel}>
        {strings.origin}
        <div style={styles.segment} role="group" aria-label={strings.origin}>
          {originOptions.map(([value, label]) => (
            <button key={value} type="button" style={styles.segmentButton(f.origin === value)} aria-pressed={f.origin === value} onClick={() => set({ origin: value })}>
              {label}
            </button>
          ))}
        </div>
      </div>
      <label style={styles.fieldLabel}>
        {strings.kind}
        <select style={{ ...styles.input, minWidth: 150 }} value={f.kind} onChange={(e) => set({ kind: e.target.value })}>
          {kindOptions.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
      </label>
      <label style={styles.fieldLabel}>
        {strings.source}
        <select style={{ ...styles.input, minWidth: 150 }} value={f.source} onChange={(e) => set({ source: e.target.value })}>
          {sourceOptions.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
      </label>
      <label style={{ display: 'inline-flex', alignItems: 'center', gap: 8, minHeight: 44, fontSize: 14, color: 'var(--arpn-fg2)' }}>
        <input type="checkbox" style={{ width: 18, height: 18 }} checked={f.includeDeleted} onChange={(e) => set({ includeDeleted: e.target.checked })} />
        {strings.showDeleted}
      </label>
    </form>
  )

  const filtersPhone = (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
      <label style={{ display: 'block' }} htmlFor={searchId}>
        <span style={{ position: 'absolute', left: -9999 }}>{strings.searchPhone}</span>
        <input id={searchId} type="search" style={{ ...styles.input, width: '100%', fontSize: 15 }} placeholder={strings.searchPhone} value={f.q} onChange={(e) => set({ q: e.target.value })} />
      </label>
      <div role="group" aria-label={strings.filterLabel} style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
        {originOptions.map(([value, label]) => (
          <button key={value} type="button" style={styles.filterChip(f.origin === value)} aria-pressed={f.origin === value} onClick={() => set({ origin: value })}>
            {label}
          </button>
        ))}
        <MenuChip label={strings.kind} value={f.kind} options={kindOptions} onChange={(kind) => set({ kind })} strings={strings} testId="kind" />
        <MenuChip label={strings.source} value={f.source} options={sourceOptions} onChange={(source) => set({ source })} strings={strings} testId="source" />
        <button type="button" style={styles.filterChip(f.includeDeleted)} aria-pressed={f.includeDeleted} onClick={() => set({ includeDeleted: !f.includeDeleted })}>
          {strings.showDeleted}
        </button>
      </div>
    </div>
  )

  return (
    <div ref={ref} style={{ ...styles.root, display: 'flex', flexDirection: 'column', gap: phone ? 12 : 20 }} data-notes-list="" data-layout={phone ? 'phone' : 'desktop'}>
      {showHeading ? (
        <div style={{ display: 'flex', alignItems: phone ? 'center' : 'flex-end', gap: 16, flexWrap: 'wrap' }}>
          <div style={{ flex: 1, minWidth: 0 }}>
            <h1 style={{ margin: 0, fontSize: phone ? 24 : 28, fontWeight: 700, letterSpacing: '-0.01em' }}>{strings.title}</h1>
            {phone ? null : <p style={{ ...styles.muted, margin: '4px 0 0' }}>{strings.subtitle}</p>}
          </div>
          {phone ? null : <SyncLine sources={syncSources} strings={strings} now={clock} phone={false} />}
          {onNew ? (
            <button type="button" style={{ ...styles.button, ...styles.buttonPrimary, ...(phone ? { width: 44, padding: 0, borderRadius: 999 } : {}) }} onClick={onNew} aria-label={phone ? strings.newNote : undefined}>
              <PlusIcon size={phone ? 22 : 16} />
              {phone ? null : strings.newNote}
            </button>
          ) : null}
        </div>
      ) : null}
      {phone ? filtersPhone : filtersDesktop}
      {phone ? <SyncLine sources={syncSources} strings={strings} now={clock} phone /> : null}

      {errorText ? (
        <div role="alert" style={{ ...styles.card, padding: '12px 16px', background: 'var(--arpn-del-bg)', color: 'var(--arpn-del-fg)', borderColor: 'var(--arpn-del-bg)' }}>
          {strings.errorPrefix}: {errorText}
        </div>
      ) : null}

      {loading && !hasItems ? (
        <div role="status" style={{ ...styles.muted, padding: '24px 0', textAlign: 'center' }}>
          {strings.loading}
        </div>
      ) : null}

      {!loading && !errorText && !hasItems ? (
        active ? (
          <div style={{ ...styles.card, padding: '32px 24px', textAlign: 'center' }} data-no-matches="">
            <h2 style={{ margin: 0, fontSize: 18 }}>{strings.noMatches}</h2>
            <p style={{ ...styles.muted, margin: '6px 0 12px' }}>{strings.noMatchesHint}</p>
            <button type="button" style={styles.button} onClick={() => onFiltersChange?.({ ...EMPTY_FILTERS })}>
              {strings.clearFilters}
            </button>
          </div>
        ) : (
          <EmptyState strings={strings} onNew={onNew} howSyncingHref={howSyncingHref} phone={phone} />
        )
      ) : null}

      {hasItems ? (
        <div style={{ ...styles.card, overflow: 'hidden' }}>
          {groups.map(([key, notes]) => {
            const headingId = `${searchId}-${key}`
            return (
              <section key={key} aria-labelledby={headingId}>
                <h2 id={headingId} style={{ ...styles.sectionHeading, padding: '12px 20px', background: 'var(--arpn-surface)' }}>
                  {strings.monthHeader(monthTitle(key), notes.length)}
                </h2>
                <ul style={{ margin: 0, padding: 0 }}>
                  {notes.map((note) => (
                    <Row key={note.id} note={note} strings={strings} now={clock} hrefForNote={hrefForNote} isEmpty={isEmpty} phone={phone} onAttachmentExpired={onAttachmentExpired} />
                  ))}
                </ul>
              </section>
            )
          })}
        </div>
      ) : null}

      {hasItems && onLoadMore ? (
        <button type="button" style={{ ...styles.button, alignSelf: 'center' }} onClick={onLoadMore} disabled={loading}>
          {loading ? strings.loading : strings.loadMore}
        </button>
      ) : null}
    </div>
  )
}
