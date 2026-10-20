// ProposalReview (C6c ga-mxal.33; ADR §3.4 step 3, K§3, K§4 bands, K§8 presentations).
//
// The user reviews a Proposal and the component emits a ConfirmBody. It never fetches: data and
// callbacks come in through props.
//
//   proposal        Proposal (arp_notes/schemas/Proposal.json)
//   presentation    'dialog' | 'sheet' | 'formsheet' | 'auto' (default). auto: <600 px sheet,
//                   <1024 px form sheet, else dialog.
//   onConfirm(body)     ConfirmBody, exactly what the user accepted (K§2/K§3).
//   onDecideLater()     Esc, the close button and "Decide later". No data call: the cached proposal stays.
//   onRejectAll(body)   "Reject all". body is a ConfirmBody with every proposed target in `rejected`.
//   onSomeday?(mention, enabled)  Supplying it turns the "Someday" switches on (K§5) and adds
//                   `someday` to the ConfirmBody; without it the unresolved list is read-only.
//   hostNote?       One muted line at the end, e.g. "Roy Howat is kept as text — he isn’t one of your teachers in PT."
//   noteTitle?      Shown in the subtitle: From “<title>” · N suggestions …
//   strings?        Overrides for any key of DEFAULT_STRINGS (strings.js).
//
// Rendered inline as a fixed-position overlay; mount it where the dialog should be inert-able, not
// inside a transformed ancestor.

import { useEffect, useId, useMemo, useReducer, useRef, useState, useSyncExternalStore } from 'react'
import { countWord, fmt, makeStrings } from './strings.js'
import { CSS } from './styles.js'
import {
  buildModel,
  derive,
  duplicateCount,
  initialState,
  reduce,
  rejectAllBody,
  resolvePresentation,
  visibleRows,
  COLLAPSE_AFTER,
} from './model.js'

const FOCUSABLE =
  'button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), a[href], [tabindex]:not([tabindex="-1"])'

function subscribeWidth(callback) {
  window.addEventListener('resize', callback)
  return () => window.removeEventListener('resize', callback)
}
const widthSnapshot = () => window.innerWidth
const serverWidth = () => 1280

function Icon({ d, children }) {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      {d ? <path d={d} /> : children}
    </svg>
  )
}

const Cross = () => <Icon d="M6 6l12 12M18 6L6 18" />

export function ProposalReview(props) {
  const { proposal } = props
  const [snapshot, setSnapshot] = useState({ proposal, key: 0 })
  // A different proposal is a different review: reset every tick, pick and lane.
  if (snapshot.proposal !== proposal) setSnapshot({ proposal, key: snapshot.key + 1 })
  const model = useMemo(() => buildModel(proposal), [proposal])
  return <Review key={snapshot.key} {...props} model={model} />
}

function Review({
  model,
  presentation = 'auto',
  onConfirm,
  onDecideLater,
  onRejectAll,
  onSomeday,
  hostNote,
  noteTitle,
  strings: stringOverrides,
}) {
  const uid = useId()
  const s = useMemo(() => makeStrings(stringOverrides), [stringOverrides])
  const t = (key, values) => fmt(s[key], values)
  const width = useSyncExternalStore(subscribeWidth, widthSnapshot, serverWidth)
  const mode = resolvePresentation(presentation, width)
  const somedayEnabled = typeof onSomeday === 'function'

  const [state, dispatch] = useReducer(reduce, model, (m) => initialState(m))
  const result = derive(model, state, { somedayEnabled })

  const dialogRef = useRef(null)
  const latest = useRef({})
  latest.current = { onDecideLater }

  // Focus: move into the dialog on open, trap Tab, Esc = Decide later, restore on close.
  useEffect(() => {
    const dialog = dialogRef.current
    const opener = document.activeElement
    dialog?.focus({ preventScroll: true })

    function onKeyDown(event) {
      if (!dialog?.isConnected) return // a review the host unmounted without React noticing
      if (event.key === 'Escape') {
        event.preventDefault()
        latest.current.onDecideLater?.()
        return
      }
      if (event.key !== 'Tab') return
      const items = [...dialog.querySelectorAll(FOCUSABLE)]
      if (!items.length) {
        event.preventDefault()
        return
      }
      const first = items[0]
      const last = items[items.length - 1]
      const active = document.activeElement
      if (!dialog.contains(active) || active === dialog) {
        event.preventDefault()
        ;(event.shiftKey ? last : first).focus()
      } else if (event.shiftKey && active === first) {
        event.preventDefault()
        last.focus()
      } else if (!event.shiftKey && active === last) {
        event.preventDefault()
        first.focus()
      }
    }
    function onFocusIn(event) {
      if (dialog?.isConnected && !dialog.contains(event.target)) dialog.focus({ preventScroll: true })
    }
    document.addEventListener('keydown', onKeyDown)
    document.addEventListener('focusin', onFocusIn)
    return () => {
      document.removeEventListener('keydown', onKeyDown)
      document.removeEventListener('focusin', onFocusIn)
      if (opener instanceof HTMLElement && opener.isConnected) opener.focus({ preventScroll: true })
    }
  }, [])

  const titleId = `${uid}-title`
  const bannerId = `${uid}-banner`
  const sectionName = (section) => {
    const group = { pieces: 'sectionPieces', composers: 'sectionComposers', techniques: 'sectionTechniques' }[
      section.group
    ]
    return `${s[group ?? 'sectionOther']} · ${s[`band${cap(section.band)}`]}`
  }

  const linkSections = model.sections.map((section) => (
    <LinkSection key={section.id} section={section} name={sectionName(section)} {...{ state, dispatch, s, t }} />
  ))
  const pickSection = model.picks.length > 0 && (
    <section key="pick" className="arpn-rv__sec" aria-label={s.sectionPick}>
      <SectionHead title={s.sectionPick} count={model.picks.length} />
      {model.picks.map((pick) => (
        <PickGroup key={pick.key} pick={pick} uid={uid} {...{ state, dispatch, s, t }} />
      ))}
    </section>
  )
  const unresolvedSection = model.unresolved.length > 0 && (
    <section key="unresolved" className="arpn-rv__sec" aria-label={s.sectionUnresolved}>
      <SectionHead title={s.sectionUnresolved} count={model.unresolved.length} />
      <p className="arpn-rv__help">{somedayEnabled ? s.unresolvedHelpSomeday : s.unresolvedHelp}</p>
      {model.unresolved.map((u) => (
        <UnresolvedRow
          key={u.key}
          entry={u}
          on={Boolean(state.someday[u.key])}
          enabled={somedayEnabled}
          onToggle={(value) => {
            dispatch({ type: 'someday', key: u.key, value })
            onSomeday?.(
              {
                mention: u.item.mention,
                kind_hint: u.item.kind_hint ?? null,
                composer_label: u.item.composer_label ?? null,
                anchor: u.item.anchor ?? null,
                quote: u.item.quote ?? null,
              },
              value,
            )
          }}
          t={t}
        />
      ))}
    </section>
  )
  const actionSection = model.actions.length > 0 && (
    <section key="actions" className="arpn-rv__sec" aria-label={s.sectionActions}>
      <SectionHead
        title={s.sectionActions}
        count={model.actions.length}
        toggle={{
          anyOn: model.actions.some((a) => state.actionOn[a.key]),
          onClick: (value) => dispatch({ type: 'setActions', keys: model.actions.map((a) => a.key), value }),
        }}
        s={s}
        t={t}
      />
      {model.actions.map((a) => (
        <ActionRow key={a.key} entry={a} {...{ state, dispatch, s, t }} />
      ))}
    </section>
  )
  const note = hostNote ? (
    <p key="host" className="arpn-rv__host">
      {hostNote}
    </p>
  ) : null

  const subtitle = noteTitle
    ? t('subtitleWithTitle', { title: noteTitle, n: model.total })
    : t('subtitle', { n: model.total })

  return (
    <div className="arpn-rv" data-presentation={mode}>
      <style>{CSS}</style>
      <div className="arpn-rv__scrim" aria-hidden="true" onMouseDown={(e) => e.preventDefault()} />
      <section
        ref={dialogRef}
        className="arpn-rv__dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={bannerId}
        tabIndex={-1}
      >
        {mode === 'sheet' && (
          <div className="arpn-rv__grab" aria-hidden="true">
            <span />
          </div>
        )}
        <div className="arpn-rv__head">
          <div className="arpn-rv__head-text">
            <h2 id={titleId} className="arpn-rv__title">
              {s.title}
            </h2>
            <p className="arpn-rv__sub">{subtitle}</p>
          </div>
          <button type="button" className="arpn-rv__ib arpn-rv__ib--close" aria-label={s.close} onClick={() => onDecideLater?.()}>
            <Cross />
          </button>
        </div>
        <div id={bannerId} className="arpn-rv__banner">
          <Icon>
            <circle cx="12" cy="12" r="9" />
            <path d="M12 8v5M12 16h.01" />
          </Icon>
          <span>
            <b>{s.bannerStrong}</b> {s.banner}
          </span>
        </div>
        <div className="arpn-rv__body">
          {mode === 'dialog' ? (
            <div className="arpn-rv__cols">
              <div className="arpn-rv__col">{linkSections}</div>
              <div className="arpn-rv__col">
                {pickSection}
                {unresolvedSection}
                {actionSection}
                {note}
              </div>
            </div>
          ) : (
            <div className="arpn-rv__col">
              {pickSection}
              {linkSections}
              {unresolvedSection}
              {actionSection}
              {note}
            </div>
          )}
        </div>
        <div className="arpn-rv__foot">
          <p className="arpn-rv__summary" aria-live="polite">
            <b>
              {t('creates', {
                links: t(result.linkCount === 1 ? 'linksOne' : 'linksMany', { n: result.linkCount }),
                backlog: t(result.backlogCount === 1 ? 'backlogOne' : 'backlogMany', { n: result.backlogCount }),
              })}
            </b>{' '}
            <span className="arpn-rv__muted">{summaryTail(result, somedayEnabled, t)}</span>
          </p>
          <div className="arpn-rv__actions">
            <button type="button" className="arpn-rv__btn arpn-rv__btn--danger" onClick={() => onRejectAll?.(rejectAllBody(model))}>
              {s.rejectAll}
            </button>
            <button type="button" className="arpn-rv__btn" onClick={() => onDecideLater?.()}>
              {s.decideLater}
            </button>
            <button
              type="button"
              className="arpn-rv__btn arpn-rv__btn--primary"
              disabled={result.empty}
              onClick={() => onConfirm?.(result.body)}
            >
              {result.confirmCount > 0 ? t('confirm', { n: result.confirmCount }) : s.confirmEmpty}
            </button>
          </div>
        </div>
      </section>
    </div>
  )
}

const cap = (word) => word.charAt(0).toUpperCase() + word.slice(1)

function summaryTail(result, somedayEnabled, t) {
  const parts = result.pickSummary.map((p) =>
    t({ picked: 'pickPicked', skipped: 'pickSkipped', later: 'pickLater' }[p.state], { name: p.name }),
  )
  if (somedayEnabled) {
    parts.push(t(result.somedayCount === 1 ? 'somedaySummaryOne' : 'somedaySummaryMany', { n: result.somedayCount }))
  }
  return parts.join(' ')
}

function SectionHead({ title, count, toggle, s, t }) {
  return (
    <div className="arpn-rv__sh">
      <h3>{title}</h3>
      <span className="arpn-rv__n">{count}</span>
      <span className="arpn-rv__grow" />
      {toggle && (
        <button
          type="button"
          className="arpn-rv__btn arpn-rv__btn--link"
          aria-label={t(toggle.anyOn ? 'untickAllLabel' : 'tickAllLabel', { section: title })}
          onClick={() => toggle.onClick(!toggle.anyOn)}
        >
          {toggle.anyOn ? s.untickAll : s.tickAll}
        </button>
      )}
    </div>
  )
}

function LinkSection({ section, name, state, dispatch, s, t }) {
  const rows = visibleRows(section, state)
  const hidden = section.rows.length - rows.length
  const expanded = Boolean(state.expanded[section.id])
  const live = section.rows.filter((r) => !state.rejected[r.key])
  const anyOn = live.some((r) => state.ticked[r.key])
  const keys = live.map((r) => r.key)
  return (
    <section className="arpn-rv__sec" aria-label={name}>
      <div className="arpn-rv__sh">
        <h3>{name}</h3>
        <span className="arpn-rv__n">{section.rows.length}</span>
        <span className="arpn-rv__grow" />
        <button
          type="button"
          className="arpn-rv__btn arpn-rv__btn--link"
          aria-label={t(anyOn ? 'untickAllLabel' : 'tickAllLabel', { section: name })}
          onClick={() => dispatch({ type: 'setSection', keys, value: !anyOn })}
        >
          {anyOn ? s.untickAll : s.tickAll}
        </button>
      </div>
      {rows.map((row) => (
        <LinkRow key={row.key} row={row} {...{ state, dispatch, s, t }} />
      ))}
      {section.rows.length > COLLAPSE_AFTER && (
        <button
          type="button"
          className="arpn-rv__btn arpn-rv__btn--link arpn-rv__btn--more"
          aria-expanded={expanded}
          onClick={() => dispatch({ type: 'expand', key: section.id })}
        >
          {expanded ? s.showFewer : t('showMore', { n: hidden })}
        </button>
      )}
    </section>
  )
}

const BADGE_KEY = { high: 'badgeHigh', medium: 'badgeMedium', low: 'badgeLow' }

function LinkRow({ row, state, dispatch, s, t }) {
  const { link } = row
  const rejected = Boolean(state.rejected[row.key])
  const target = link.entity_label
  const detail =
    link.mention_count != null
      ? link.mention_count === 1
        ? s.mentionOnce
        : t('mentionCount', { n: link.mention_count })
      : `“${link.quote}”`
  return (
    <div className="arpn-rv__row" data-rejected={rejected || undefined}>
      <input
        type="checkbox"
        checked={!rejected && Boolean(state.ticked[row.key])}
        disabled={rejected}
        aria-label={t(rejected ? 'linkToRejected' : 'linkTo', { target })}
        onChange={() => dispatch({ type: 'toggle', key: row.key })}
      />
      <div className="arpn-rv__grow">
        <div className="arpn-rv__line">
          <span className={`arpn-rv__chip${rejected ? ' arpn-rv__chip--struck' : ''}`}>{target}</span>
          {rejected ? (
            <span className="arpn-rv__badge arpn-rv__badge--rejected">{s.rejected}</span>
          ) : (
            <span className={`arpn-rv__badge arpn-rv__badge--${row.band}`}>{s[BADGE_KEY[row.band]]}</span>
          )}
        </div>
        <div className="arpn-rv__q">{detail}</div>
      </div>
      {/* One button for both states, so focus stays on it when it flips between Reject and Undo. */}
      <button
        type="button"
        className={`arpn-rv__ib${rejected ? ' arpn-rv__ib--undo' : ''}`}
        aria-label={t(rejected ? 'undoLabel' : 'reject', { target })}
        onClick={() => dispatch({ type: rejected ? 'undo' : 'reject', key: row.key })}
      >
        {rejected ? s.undo : <Cross />}
      </button>
    </div>
  )
}

function PickGroup({ pick, uid, state, dispatch, s, t }) {
  const { link, candidates } = pick
  const choice = state.picks[pick.key]
  const name = `${uid}-${pick.key}`
  const dup = duplicateCount(candidates)
  const set = (value) => dispatch({ type: 'pick', key: pick.key, value })
  return (
    <div className="arpn-rv__well" role="radiogroup" aria-label={t('pickGroup', { quote: link.quote })}>
      <p className="arpn-rv__lead">
        “{link.quote}” · {t('pickMatches', { n: candidates.length })}
      </p>
      {candidates.map((c, i) => (
        <label key={`${c.entity_type}:${c.entity_id}`} className="arpn-rv__row">
          <input type="radio" name={name} checked={choice === i} onChange={() => set(i)} />
          <span className="arpn-rv__grow">
            <b>{c.entity_label}</b>
            <span className="arpn-rv__muted">
              {c.composer_label ? ` · ${c.composer_label}` : ''} · #{c.entity_id}
            </span>
          </span>
        </label>
      ))}
      <label className="arpn-rv__row">
        <input type="radio" name={name} checked={choice === 'skip'} onChange={() => set('skip')} />
        <span className="arpn-rv__grow">{s.pickNone}</span>
      </label>
      {dup > 0 && <div className="arpn-rv__dup">{fmt(s.duplicateHint, countWord(dup))}</div>}
    </div>
  )
}

function UnresolvedRow({ entry, on, enabled, onToggle, t }) {
  const { item } = entry
  const sub = item.composer_label ?? item.kind_hint
  return (
    <div className="arpn-rv__row arpn-rv__row--center">
      <div className="arpn-rv__grow">
        <b>{item.mention}</b>
        {sub ? <span className="arpn-rv__muted"> · {sub}</span> : null}
      </div>
      {enabled && (
        <label className="arpn-rv__tog">
          <input
            type="checkbox"
            checked={on}
            aria-label={t('somedayLabel', { name: item.mention })}
            onChange={(e) => onToggle(e.target.checked)}
          />
          {t('someday')}
        </label>
      )}
    </div>
  )
}

function ActionRow({ entry, state, dispatch, s, t }) {
  const { action, key, target } = entry
  const lane = state.lanes[key] ?? action.lane
  return (
    <div className="arpn-rv__row arpn-rv__row--center arpn-rv__row--action">
      <input
        type="checkbox"
        checked={Boolean(state.actionOn[key])}
        aria-label={t('addAction', { text: action.text })}
        onChange={() => dispatch({ type: 'toggleAction', key })}
      />
      <div className="arpn-rv__grow">
        <div className="arpn-rv__strong">{action.text}</div>
        {target ? <div className="arpn-rv__q">{target}</div> : null}
      </div>
      <div className="arpn-rv__seg" role="group" aria-label={s.lane}>
        {['practice', 'lesson'].map((value) => (
          <button
            key={value}
            type="button"
            aria-pressed={lane === value}
            onClick={() => dispatch({ type: 'lane', key, value })}
          >
            {value === 'practice' ? s.lanePractice : s.laneLesson}
          </button>
        ))}
      </div>
    </div>
  )
}
