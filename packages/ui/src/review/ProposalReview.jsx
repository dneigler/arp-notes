// ProposalReview: the confirm step of propose -> confirm (ADR §3.4, K§3, K§4 bands, K§8 presentations).
// It never fetches. It shows a Proposal, lets the user tick, reject, pick and set lanes, and hands the
// host a ConfirmBody. Nothing is created until the host posts that body.
import { useEffect, useId, useMemo, useRef, useState } from 'react'
import {
  COLLAPSE_AFTER,
  SKIP,
  bandsIn,
  buildModel,
  derive,
  entityKey,
  initialState,
  rejectAllBody,
} from './model.js'
import { REVIEW_STRINGS } from './strings.js'
import { makeStyles } from './styles.js'

const PRESENTATIONS = ['dialog', 'sheet', 'formsheet']

/** K§8: under 600 px a bottom sheet, under 1024 px a centred form sheet, else a dialog. */
export function presentationForWidth(width) {
  if (width < 600) return 'sheet'
  if (width < 1024) return 'formsheet'
  return 'dialog'
}

function useViewportWidth(enabled) {
  const read = () => (typeof window === 'undefined' ? 1280 : window.innerWidth)
  const [width, setWidth] = useState(read)
  useEffect(() => {
    if (!enabled) return undefined
    const onResize = () => setWidth(read())
    onResize()
    window.addEventListener('resize', onResize)
    return () => window.removeEventListener('resize', onResize)
  }, [enabled])
  return width
}

const FOCUSABLE = 'button, [href], input, select, textarea, [tabindex]'

function focusables(root) {
  return [...root.querySelectorAll(FOCUSABLE)].filter(
    (el) => !el.disabled && el.tabIndex >= 0 && !el.hidden && el.getAttribute('aria-hidden') !== 'true',
  )
}

// Modal behaviour: focus moves into the dialog, Tab stays inside, Esc is "Decide later", the page
// behind does not scroll, and focus goes back to whatever had it before.
function useModal(panelRef, onEscape) {
  const escape = useRef(onEscape)
  escape.current = onEscape
  useEffect(() => {
    const panel = panelRef.current
    const previous = document.activeElement
    const overflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    panel.focus()

    const onKeyDown = (e) => {
      if (e.key === 'Escape') {
        e.preventDefault()
        e.stopPropagation()
        escape.current()
        return
      }
      if (e.key !== 'Tab') return
      const items = focusables(panel)
      if (!items.length) {
        e.preventDefault()
        panel.focus()
        return
      }
      const first = items[0]
      const last = items[items.length - 1]
      const active = document.activeElement
      if (!panel.contains(active) || active === panel) {
        e.preventDefault()
        ;(e.shiftKey ? last : first).focus()
      } else if (e.shiftKey && active === first) {
        e.preventDefault()
        last.focus()
      } else if (!e.shiftKey && active === last) {
        e.preventDefault()
        first.focus()
      }
    }
    const onFocusIn = (e) => {
      if (!panel.contains(e.target)) (focusables(panel)[0] ?? panel).focus()
    }
    document.addEventListener('keydown', onKeyDown, true)
    document.addEventListener('focusin', onFocusIn)
    return () => {
      document.removeEventListener('keydown', onKeyDown, true)
      document.removeEventListener('focusin', onFocusIn)
      document.body.style.overflow = overflow
      if (previous && typeof previous.focus === 'function') previous.focus()
    }
  }, [panelRef])
}

function CloseIcon({ style }) {
  return (
    <svg viewBox="0 0 24 24" style={style} aria-hidden="true" focusable="false">
      <path d="M6 6l12 12M18 6L6 18" />
    </svg>
  )
}

function Heading({ s, title, count, action }) {
  return (
    <div style={s.sectionHead}>
      <h3 style={s.sectionTitle}>
        <span>{title}</span>
        {count !== undefined && <span style={s.sectionCount}>{count}</span>}
      </h3>
      <span style={s.spacer} />
      {action}
    </div>
  )
}

function LinkRow({ ctx, row }) {
  const { s, strings, state, edit, uid } = ctx
  const { i, link, band } = row
  const rejected = state.rejected.has(i)
  const id = `${uid}-l${i}`
  const label = link.entity_label
  const sub =
    link.mention_count > 1 ? strings.mentioned(link.mention_count) : link.quote ? `“${link.quote}”` : null
  return (
    <div style={s.row} data-row="link" data-rejected={rejected ? 'true' : 'false'}>
      <input
        id={id}
        type="checkbox"
        style={s.check}
        checked={!rejected && state.ticked.has(i)}
        disabled={rejected}
        aria-label={rejected ? strings.linkToRejected(label) : strings.linkTo(label)}
        onChange={() =>
          edit((n) => {
            if (n.ticked.has(i)) n.ticked.delete(i)
            else n.ticked.add(i)
          })
        }
      />
      <label htmlFor={id} style={s.rowBody}>
        <span style={s.rowHead}>
          <span style={{ ...s.chip, ...(rejected ? s.chipRejected : null) }}>{label}</span>
          <span style={s.badge(rejected ? 'rejected' : band)}>{rejected ? strings.rejected : strings.bands[band]}</span>
        </span>
        {sub && <span style={s.quote}>{sub}</span>}
      </label>
      {rejected ? (
        <button
          type="button"
          style={s.ghost}
          aria-label={strings.undoReject(label)}
          onClick={() =>
            edit((n) => {
              n.rejected.delete(i)
              if (link.confidence >= 0.5) n.ticked.add(i)
            })
          }
        >
          {strings.undo}
        </button>
      ) : (
        <button
          type="button"
          style={s.iconButton}
          aria-label={strings.reject(label)}
          onClick={() =>
            edit((n) => {
              n.rejected.add(i)
              n.ticked.delete(i)
            })
          }
        >
          <CloseIcon style={s.smallIcon} />
        </button>
      )}
    </div>
  )
}

function LinkSection({ ctx, id, title, rows }) {
  const { s, strings, state, edit, presentation } = ctx
  if (!rows.length) return null
  const bands = bandsIn(rows).map((b) => strings.bands[b].toLowerCase())
  const heading = `${title} · ${strings.sectionBand(bands)}`
  const live = rows.filter((r) => !state.rejected.has(r.i))
  const tickedCount = live.filter((r) => state.ticked.has(r.i)).length
  const anyTicked = tickedCount > 0
  const collapsible = rows.length > COLLAPSE_AFTER
  const open = state.expanded.has(id)
  const shown = collapsible && !open ? rows.slice(0, COLLAPSE_AFTER) : rows
  const count = presentation === 'sheet' ? strings.tickedOf(tickedCount, rows.length) : rows.length
  return (
    <section style={s.section} data-section={id}>
      <Heading
        s={s}
        title={heading}
        count={count}
        action={
          <button
            type="button"
            style={s.ghost}
            onClick={() =>
              edit((n) => {
                for (const r of live) {
                  if (anyTicked) n.ticked.delete(r.i)
                  else n.ticked.add(r.i)
                }
              })
            }
          >
            {anyTicked ? strings.untickAll : strings.tickAll}
          </button>
        }
      />
      {shown.map((row) => (
        <LinkRow key={row.i} ctx={ctx} row={row} />
      ))}
      {collapsible && (
        <button
          type="button"
          style={{ ...s.ghost, justifyContent: 'flex-start' }}
          aria-expanded={open}
          onClick={() =>
            edit((n) => {
              if (n.expanded.has(id)) n.expanded.delete(id)
              else n.expanded.add(id)
            })
          }
        >
          {open ? strings.showFewer : strings.showMore(rows.length - COLLAPSE_AFTER)}
        </button>
      )}
    </section>
  )
}

function PickGroup({ ctx, group }) {
  const { s, strings, state, edit, uid } = ctx
  const { i, link, candidates, duplicates } = group
  const pick = state.picks.get(i)
  const name = `${uid}-g${i}`
  const choose = (value) => edit((n) => n.picks.set(i, value))
  return (
    <div style={s.well} role="radiogroup" aria-label={strings.pickGroup(link.entity_label)} data-row="group">
      <div style={s.wellQuote}>
        {link.quote ? `“${link.quote}” · ` : ''}
        {strings.matches(candidates.length)}
      </div>
      {candidates.map((c) => {
        const key = entityKey(c.entity_type, c.entity_id)
        return (
          <label key={key} style={s.row}>
            <input
              type="radio"
              name={name}
              style={s.radio}
              checked={pick === key}
              onChange={() => choose(key)}
            />
            <span style={s.optionLabel}>
              <b>{c.entity_label}</b> <span style={s.muted}>· #{c.entity_id}</span>
            </span>
          </label>
        )
      })}
      <label style={s.row}>
        <input
          type="radio"
          name={name}
          style={s.radio}
          checked={pick === SKIP}
          onChange={() => choose(SKIP)}
        />
        <span style={s.optionLabel}>{strings.skipOption}</span>
      </label>
      {duplicates > 1 && <div style={s.hint}>{strings.duplicateHint(duplicates, link.entity_type)}</div>}
    </div>
  )
}

function PickSection({ ctx }) {
  const { s, strings, model } = ctx
  if (!model.groups.length) return null
  return (
    <section style={s.section} data-section="pick">
      <Heading s={s} title={strings.pick} count={model.groups.length} />
      <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
        {model.groups.map((g) => (
          <PickGroup key={g.i} ctx={ctx} group={g} />
        ))}
      </div>
    </section>
  )
}

function secondaryOf(item, strings) {
  if (item.composer_label) {
    const at = item.composer_label.lastIndexOf(' · ')
    return at >= 0 ? item.composer_label.slice(at + 3) : item.composer_label
  }
  return item.kind_hint ? strings.kinds[item.kind_hint] : null
}

function UnresolvedSection({ ctx }) {
  const { s, strings, model, state, edit, onSomeday, somedaySelection } = ctx
  if (!model.unresolved.length) return null
  return (
    <section style={s.section} data-section="unresolved">
      <Heading s={s} title={strings.unresolved} count={model.unresolved.length} />
      {onSomeday && <div style={s.blurb}>{strings.somedayBlurb}</div>}
      {model.unresolved.map(({ i, item }) => {
        const secondary = secondaryOf(item, strings)
        return (
          <div key={i} style={{ ...s.row, ...s.rowCentered }} data-row="unresolved">
            <div style={s.optionLabel}>
              <b>{item.mention}</b>
              {secondary && <span style={s.muted}> · {secondary}</span>}
            </div>
            {onSomeday && (
              <label style={s.toggle}>
                <input
                  type="checkbox"
                  style={s.toggleInput}
                  aria-label={strings.somedayFor(item.mention)}
                  checked={state.someday.has(i)}
                  onChange={() => {
                    const next = new Set(state.someday)
                    if (next.has(i)) next.delete(i)
                    else next.add(i)
                    edit((n) => {
                      n.someday = next
                    })
                    onSomeday(somedaySelection(next))
                  }}
                />
                {strings.someday}
              </label>
            )}
          </div>
        )
      })}
    </section>
  )
}

function ActionSection({ ctx }) {
  const { s, strings, model, state, edit, presentation } = ctx
  if (!model.actions.length) return null
  const stacked = presentation === 'sheet'
  return (
    <section style={s.section} data-section="actions">
      <Heading s={s} title={strings.actions} count={model.actions.length} />
      {model.actions.map(({ i, item }) => {
        const lane = state.lanes.get(i) ?? item.lane
        const piece =
          item.entity_type && item.entity_id !== null && item.entity_id !== undefined
            ? model.labels.get(entityKey(item.entity_type, item.entity_id))
            : null
        const seg = (
          <div style={{ ...s.seg, ...(stacked ? { display: 'flex', width: '100%' } : null) }} role="group" aria-label={strings.lane}>
            {['practice', 'lesson'].map((value) => (
              <button
                key={value}
                type="button"
                style={s.segButton(lane === value)}
                aria-pressed={lane === value}
                onClick={() => edit((n) => n.lanes.set(i, value))}
              >
                {strings[value]}
              </button>
            ))}
          </div>
        )
        const id = `${ctx.uid}-a${i}`
        return (
          <div
            key={i}
            style={{ ...s.row, ...(stacked ? s.actionStack : s.rowCentered), display: 'flex' }}
            data-row="action"
          >
            <div style={{ display: 'flex', gap: 10, alignItems: 'flex-start', width: '100%', flex: 1, minWidth: 0 }}>
              <input
                id={id}
                type="checkbox"
                style={s.check}
                checked={state.actionOn.has(i)}
                aria-label={strings.addAction(item.text)}
                onChange={() =>
                  edit((n) => {
                    if (n.actionOn.has(i)) n.actionOn.delete(i)
                    else n.actionOn.add(i)
                  })
                }
              />
              <label htmlFor={id} style={s.rowBody}>
                <span style={s.actionText}>{item.text}</span>
                <span style={s.quote}>{piece ?? strings.noPiece}</span>
              </label>
            </div>
            {seg}
          </div>
        )
      })}
    </section>
  )
}

/**
 * @param {object} props
 * @param {object} props.proposal   the Proposal to review (A.2 + K§2)
 * @param {'dialog'|'sheet'|'formsheet'|'auto'} [props.presentation='auto']
 * @param {(body: object) => void} props.onConfirm        gets the ConfirmBody
 * @param {() => void} props.onDecideLater                no call to the server; also Esc, Close and the scrim
 * @param {(body: object) => void} props.onRejectAll      gets a ConfirmBody that rejects every suggested link
 * @param {(selected: object[]) => void} [props.onSomeday]  K§5: passing it shows the Someday switches; it
 *   is called with the SomedayMention list whenever a switch changes, and ConfirmBody.someday carries it
 * @param {string} [props.hostNote]   one line from the host, e.g. a person kept as text
 * @param {string} [props.noteTitle]  the note's title, for the header ("From “<title>”")
 * @param {object} [props.strings]    overrides for REVIEW_STRINGS
 */
export function ProposalReview({
  proposal,
  presentation = 'auto',
  onConfirm,
  onDecideLater,
  onRejectAll,
  onSomeday,
  hostNote,
  noteTitle,
  strings: stringOverrides,
}) {
  const strings = useMemo(() => ({ ...REVIEW_STRINGS, ...stringOverrides }), [stringOverrides])
  const width = useViewportWidth(presentation === 'auto')
  const resolved = PRESENTATIONS.includes(presentation) ? presentation : presentationForWidth(width)
  const s = useMemo(() => makeStyles(resolved), [resolved])

  const model = useMemo(() => buildModel(proposal), [proposal])
  const [state, setState] = useState(() => initialState(model))
  const [seen, setSeen] = useState(model)
  if (seen !== model) {
    // A new proposal (a refresh) starts from its own defaults.
    setSeen(model)
    setState(initialState(model))
  }
  const edit = (fn) =>
    setState((prev) => {
      const next = {
        ticked: new Set(prev.ticked),
        rejected: new Set(prev.rejected),
        picks: new Map(prev.picks),
        someday: new Set(prev.someday),
        actionOn: new Set(prev.actionOn),
        lanes: new Map(prev.lanes),
        expanded: new Set(prev.expanded),
      }
      fn(next)
      return next
    })

  const somedayEnabled = typeof onSomeday === 'function'
  const { body, counts } = useMemo(() => derive(model, state, { somedayEnabled }), [model, state, somedayEnabled])
  const somedaySelection = (picked) =>
    derive(model, { ...state, someday: picked }, { somedayEnabled: true }).body.someday ?? []

  const uid = useId()
  const titleId = `${uid}-title`
  const panelRef = useRef(null)
  useModal(panelRef, onDecideLater)

  const ctx = { s, strings, model, state, edit, uid, presentation: resolved, onSomeday: somedayEnabled ? onSomeday : null, somedaySelection }
  const compact = resolved !== 'dialog'

  const pieces = <LinkSection key="pieces" ctx={ctx} id="pieces" title={strings.pieces} rows={model.sections.pieces} />
  const composers = (
    <LinkSection key="composers" ctx={ctx} id="composers" title={strings.composers} rows={model.sections.composers} />
  )
  const techniques = (
    <LinkSection key="techniques" ctx={ctx} id="techniques" title={strings.techniques} rows={model.sections.techniques} />
  )
  const pick = <PickSection key="pick" ctx={ctx} />
  const unresolved = <UnresolvedSection key="unresolved" ctx={ctx} />
  const actions = <ActionSection key="actions" ctx={ctx} />
  const note = hostNote ? (
    <p key="note" style={s.hostNote} data-host-note="">
      {hostNote}
    </p>
  ) : null

  const subtitle = compact
    ? strings.subtitleShort(model.total, noteTitle)
    : strings.subtitle(model.total, noteTitle)
  const pickSummary = strings.pickSummary(counts)

  const summary = (
    <div style={s.footerText} data-footer="">
      <b>{strings.creates(counts.links, counts.backlog)}</b>
      {pickSummary && <span style={s.muted}> {pickSummary}</span>}
      {somedayEnabled && <span style={s.muted}> {strings.somedayCount(counts.someday)}</span>}
    </div>
  )
  const rejectAll = (
    <button type="button" style={resolved === 'sheet' ? { ...s.buttonDanger, border: '1px solid transparent', minHeight: 40 } : s.buttonDanger} onClick={() => onRejectAll?.(rejectAllBody(model))}>
      {strings.rejectAll}
    </button>
  )
  const later = (
    <button type="button" style={{ ...s.button, ...(resolved === 'sheet' ? { flex: 1 } : null) }} onClick={() => onDecideLater?.()}>
      {strings.decideLater}
    </button>
  )
  const confirm = (
    <button type="button" style={{ ...s.buttonPrimary, ...(resolved === 'sheet' ? { flex: 2 } : null) }} onClick={() => onConfirm?.(body)}>
      {strings.confirm(counts.confirm)}
    </button>
  )

  return (
    <div
      style={s.overlay}
      data-arpn="proposal-review"
      data-presentation={resolved}
      onClick={(e) => {
        if (e.target === e.currentTarget) onDecideLater?.()
      }}
    >
      <section ref={panelRef} role="dialog" aria-modal="true" aria-labelledby={titleId} tabIndex={-1} style={s.panel}>
        {resolved === 'sheet' && (
          <div style={s.grab} aria-hidden="true">
            <span style={s.grabBar} />
          </div>
        )}
        <div style={s.header}>
          <div style={s.headerText}>
            <h2 id={titleId} style={s.title}>
              {strings.title}
            </h2>
            <div style={s.subtitle}>{subtitle}</div>
          </div>
          <button type="button" style={s.close} aria-label={strings.close} onClick={() => onDecideLater?.()}>
            <CloseIcon style={s.icon} />
          </button>
        </div>
        <div style={s.banner} data-banner="">
          <b>{strings.bannerLead}</b>
          {resolved === 'dialog' && ` ${strings.bannerDetail}`}
          {resolved === 'formsheet' && ` ${strings.bannerDetailCompact}`}
        </div>
        <div style={s.body} data-body="">
          {resolved === 'dialog' ? (
            <>
              <div style={s.column}>
                {pieces}
                {composers}
                {techniques}
              </div>
              <div style={s.column}>
                {pick}
                {unresolved}
                {actions}
                {note}
              </div>
            </>
          ) : (
            <>
              {pick}
              {pieces}
              {composers}
              {techniques}
              {unresolved}
              {actions}
              {note}
            </>
          )}
        </div>
        <div style={s.footer}>
          {summary}
          {resolved === 'sheet' ? (
            <>
              <div style={s.footerButtons}>
                {later}
                {confirm}
              </div>
              <div style={{ display: 'flex', justifyContent: 'center' }}>{rejectAll}</div>
            </>
          ) : (
            <>
              {rejectAll}
              {later}
              {confirm}
            </>
          )}
        </div>
      </section>
    </div>
  )
}
