// NoteDetailHeader: the top of a note page. Origin and kind badges, title, meta, where it came from
// and how to edit it there, the "Review N picks" entry, Export, and the "Source deleted" state with
// Keep copy / Delete from <host>… (NoteDesk, NotePhone). It never fetches: the host acts through
// callbacks, and may return a promise from any of them.
import { useEffect, useMemo, useRef, useState } from 'react'
import { ConfirmDialog } from './ConfirmDialog.jsx'
import { ChevronRightIcon, ExternalIcon, SyncIcon } from './icons.jsx'
import { durationMinutes, formatClock, formatDayMonth, formatNoteDate, kindLabel, safeHref, sourceFolder, systemLabel } from './format.js'
import { useIsPhone } from './hooks.js'
import { OriginBadge, activityLabel, originKind } from './parts.jsx'
import { styles } from './styles.js'
import { withStrings } from './strings.js'

const WORK_TYPES = ['repertoire', 'work', 'piece']

function firstName(person) {
  const first = String(person ?? '').trim().split(/\s+/)[0] ?? ''
  // 'Dr. Smith' keeps its title: a first token ending in a dot is not a given name.
  return first.endsWith('.') ? String(person).trim() : first
}

/** The label of the piece the note is mostly about: the first confirmed work link, else any link. */
function mainLinkLabel(note) {
  const links = (note.links ?? []).filter((l) => l.status !== 'rejected' && l.entity_label)
  const link = links.find((l) => WORK_TYPES.includes(l.entity_type)) ?? links[0]
  return link ? link.entity_label.split(' · ')[0] : ''
}

function keptLinkCount(note) {
  if (Array.isArray(note.links)) return note.links.filter((l) => l.status !== 'rejected').length
  return note.link_count ?? 0
}

/** Runs an async host callback, tracking busy/error. Safe if the component unmounts meanwhile. */
function useAction() {
  const [state, setState] = useState({ busy: false, error: '' })
  const alive = useRef(true)
  useEffect(() => {
    alive.current = true
    return () => {
      alive.current = false
    }
  }, [])
  const run = async (fn, failure) => {
    setState({ busy: true, error: '' })
    try {
      await fn()
      if (alive.current) setState({ busy: false, error: '' })
      return true
    } catch {
      if (alive.current) setState({ busy: false, error: failure })
      return false
    }
  }
  return [state, run]
}

function metaLine(note, strings, phone) {
  const parts = []
  const date = formatNoteDate(note.note_date)
  if (date) parts.push(phone ? date.replace(/ \d{4}$/, '') : date)
  const minutes = durationMinutes(note)
  if (minutes != null) parts.push(strings.minutes(minutes))
  if (note.person) parts.push(phone ? note.person : strings.withPerson(note.person))
  if (!phone && originKind(note) === 'source') {
    const folder = (sourceFolder(note.source_path) ?? '').replace(/\/$/, '')
    const where = [note.source_workspace, folder].filter(Boolean).join(' / ')
    if (where) parts.push(where)
  }
  return parts.join(' · ')
}

function TombstoneBlock({ note, strings, hostName, phone, onKeepCopy, onDeleteFromHost, timeZone }) {
  const system = systemLabel(note.source_system) || 'source'
  const where = note.source_system === 'obsidian' || !note.source_system ? strings.yourVault : system
  const label = mainLinkLabel(note)
  const person = note.person ? firstName(note.person) : ''
  const deletedOn = formatDayMonth(note.deleted_at, timeZone)
  const syncedWhen = [formatDayMonth(note.last_synced_at, timeZone), formatClock(note.last_synced_at, timeZone)].filter(Boolean).join(', ')
  const [keep, runKeep] = useAction()
  const [del, runDelete] = useAction()
  const [confirming, setConfirming] = useState(false)
  const busy = keep.busy || del.busy
  const host = hostName || strings.defaultHostName

  return (
    <>
      <section
        role="status"
        style={{ borderRadius: 14, background: 'var(--arpn-del-bg)', color: 'var(--arpn-del-fg)', padding: 14, display: 'flex', flexDirection: 'column', gap: 6 }}
        data-tombstone=""
      >
        <div style={{ fontWeight: 700, fontSize: 15 }}>{strings.deletedIn(system, deletedOn)}</div>
        <div style={{ fontSize: 14 }}>{strings.deletedBody(where, label, person)}</div>
        <div style={{ fontSize: 14 }}>{strings.deletedRestore}</div>
      </section>

      {onKeepCopy || onDeleteFromHost ? (
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          {onKeepCopy ? (
            <button
              type="button"
              style={{ ...styles.button, flex: phone ? 1 : undefined }}
              disabled={busy}
              onClick={() => runKeep(() => onKeepCopy(note), strings.keepFailed)}
            >
              {keep.busy ? strings.working : strings.keepCopy}
            </button>
          ) : null}
          {onDeleteFromHost ? (
            <button
              type="button"
              style={{ ...styles.button, ...styles.buttonDanger, flex: phone ? 1 : undefined }}
              disabled={busy}
              onClick={() => setConfirming(true)}
              aria-haspopup="dialog"
            >
              {strings.deleteFromHost(host)}
            </button>
          ) : null}
        </div>
      ) : null}
      {keep.error ? (
        <div role="alert" style={{ ...styles.muted, color: 'var(--arpn-del-fg)', fontSize: 13 }}>
          {keep.error}
        </div>
      ) : null}

      <div style={{ ...styles.muted, fontSize: 13 }}>{strings.lastSyncedKept(syncedWhen, keptLinkCount(note))}</div>

      {confirming ? (
        <ConfirmDialog
          title={strings.confirmDeleteTitle(host)}
          body={strings.confirmDeleteBody(host, keptLinkCount(note))}
          confirmLabel={strings.confirmDelete(host)}
          cancelLabel={strings.cancel}
          busyLabel={strings.working}
          busy={del.busy}
          error={del.error}
          onCancel={() => setConfirming(false)}
          onConfirm={async () => {
            if (await runDelete(() => onDeleteFromHost(note), strings.deleteFailed)) setConfirming(false)
          }}
        />
      ) : null}
    </>
  )
}

/**
 * @param {Object} props
 * @param {import('../api/types.js').Note} props.note
 * @param {{export?: boolean}} [props.capabilities]  GET /notes/capabilities; Export shows when `export` is true.
 * @param {(note: import('../api/types.js').Note) => void} [props.onReview]  Opens ProposalReview; without it no review entry shows.
 * @param {(note: import('../api/types.js').Note) => void} [props.onExport]
 * @param {(note: import('../api/types.js').Note) => void|Promise<void>} [props.onKeepCopy]  resolve_tombstone 'keep'.
 * @param {(note: import('../api/types.js').Note) => void|Promise<void>} [props.onDeleteFromHost]  resolve_tombstone 'delete'; runs after the in-component confirm.
 * @param {string} [props.hostName]  Names the app in 'Delete from <host>…' ('PT' on a phone, 'Practice Tracker' on a desktop).
 * @param {'auto'|'desktop'|'phone'} [props.layout]
 * @param {number} [props.now]  Epoch ms for relative times (tests).
 * @param {string} [props.timeZone]  IANA zone for clock times; default the viewer's.
 * @param {Partial<import('./strings.js').STRINGS>} [props.strings]
 */
export function NoteDetailHeader({
  note,
  capabilities,
  onReview,
  onExport,
  onKeepCopy,
  onDeleteFromHost,
  hostName,
  layout = 'auto',
  now,
  timeZone,
  strings: stringOverrides,
}) {
  const strings = useMemo(() => withStrings(stringOverrides), [stringOverrides])
  const [ref, phone] = useIsPhone(layout)
  const origin = originKind(note)
  const deleted = Boolean(note.deleted_at)
  const pending = deleted ? 0 : (note.review_pending ?? 0)
  const system = systemLabel(note.source_system) || 'source'
  const href = origin === 'source' ? safeHref(note.source_url) : null
  const activity = activityLabel(note, strings, now ?? Date.now())
  const canExport = Boolean(capabilities?.export && onExport)

  const badges = deleted ? (
    <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
      <span style={styles.badge('del')} data-badge="deleted">
        {strings.sourceDeleted}
      </span>
      <OriginBadge note={note} strings={strings} readOnly short={phone} />
    </div>
  ) : (
    <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
      <OriginBadge note={note} strings={strings} readOnly short={phone} />
      <span style={styles.badge('neu')} data-badge="kind">
        {kindLabel(note.kind)}
      </span>
    </div>
  )

  const syncLine =
    origin === 'source' ? (
      <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap', fontSize: phone ? 13 : 14, color: 'var(--arpn-fg2)' }} data-sync-info="">
        {phone ? null : <SyncIcon />}
        <span>{activity}</span>
        {href ? (
          <>
            <span aria-hidden="true">·</span>
            <a href={href} style={{ ...styles.link, display: 'inline-flex', gap: 4, alignItems: 'center', fontWeight: 600 }}>
              {strings.openIn(system)}
              {phone ? null : <ExternalIcon size={14} />}
            </a>
          </>
        ) : null}
        {phone ? null : <span style={styles.muted}>· {strings.editThere}</span>}
      </div>
    ) : activity ? (
      <div style={{ fontSize: phone ? 13 : 14, color: 'var(--arpn-fg2)' }}>{activity}</div>
    ) : null

  const reviewButton =
    pending > 0 && onReview ? (
      phone ? (
        <button
          type="button"
          onClick={() => onReview(note)}
          style={{ ...styles.button, ...styles.buttonReview, width: '100%', minHeight: 48, justifyContent: 'flex-start', borderRadius: 12, padding: '0 12px' }}
          data-review-entry=""
        >
          <span style={{ flex: 1, textAlign: 'left' }}>{strings.needsPick(pending)}</span>
          {strings.reviewShort}
          <ChevronRightIcon size={16} />
        </button>
      ) : (
        <button type="button" onClick={() => onReview(note)} style={{ ...styles.button, ...styles.buttonReview }} data-review-entry="">
          {strings.reviewPicks(pending)}
        </button>
      )
    ) : null
  const exportButton = canExport ? (
    <button type="button" style={{ ...styles.button, ...(phone ? { alignSelf: 'flex-start' } : null) }} onClick={() => onExport(note)} data-export="">
      {strings.export}
    </button>
  ) : null

  const body = (
    <>
      {badges}
      <h1 style={{ margin: 0, fontSize: phone ? 22 : 28, fontWeight: 700, lineHeight: 1.25, overflowWrap: 'anywhere' }}>{note.title}</h1>
      {deleted ? (
        <TombstoneBlock
          note={note}
          strings={strings}
          hostName={hostName}
          phone={phone}
          onKeepCopy={onKeepCopy}
          onDeleteFromHost={onDeleteFromHost}
          timeZone={timeZone}
        />
      ) : (
        <>
          <div style={{ ...styles.muted, fontSize: phone ? 13 : 14 }}>{metaLine(note, strings, phone)}</div>
          {syncLine}
        </>
      )}
    </>
  )

  if (phone) {
    return (
      <section ref={ref} style={{ ...styles.root, display: 'flex', flexDirection: 'column', gap: 10 }} data-note-header="" data-layout="phone" data-deleted={deleted ? '' : undefined}>
        {body}
        {reviewButton}
        {exportButton}
      </section>
    )
  }
  return (
    <section
      ref={ref}
      style={{ ...styles.root, ...styles.card, padding: '20px 24px', display: 'flex', gap: 24, alignItems: 'flex-start' }}
      data-note-header=""
      data-layout="desktop"
      data-deleted={deleted ? '' : undefined}
    >
      <div style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column', gap: 8 }}>{body}</div>
      {reviewButton || exportButton ? (
        <div style={{ display: 'flex', gap: 8 }}>
          {reviewButton}
          {exportButton}
        </div>
      ) : null}
    </section>
  )
}
