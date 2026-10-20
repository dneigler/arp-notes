// NoteRail: the right-hand rail of a note page (stacked below the body on a phone). Linked pieces
// grouped by work with their movement numbers, Composers, Action items with lane badges, an Images
// grid with the signed-URL note, and the note's Properties from its frontmatter. It never fetches.
import { useMemo, useState } from 'react'
import { formatBytes, kindLabel } from './format.js'
import { EntityChip } from './parts.jsx'
import { styles } from './styles.js'
import { withStrings } from './strings.js'

/** Entity types the rail groups. Hosts with other vocabularies pass `entityGroups`. */
export const DEFAULT_ENTITY_GROUPS = {
  works: ['repertoire', 'work', 'piece'],
  parts: ['movement', 'section'],
  composers: ['composer'],
}

export const IMAGE_GRID_LIMIT = 10

const SEPARATOR = ' · '
// 'Nº 3', 'No. 3', 'N° 3' -> '3'. 'II' and 'Allegro' stay as written.
const NUMBER_PREFIX = /^(?:N[º°o]\.?|No\.?|#)\s*/i

function partText(label) {
  return label.replace(NUMBER_PREFIX, '').trim()
}

const isNumber = (text) => /^\d+$/.test(text)

/** 'Nº 1, 3, 5' when every part is a number, otherwise the parts as written ('II'). */
export function partsSummary(parts, prefix = 'Nº') {
  if (!parts.length) return ''
  if (parts.every(isNumber)) return `${prefix} ${[...parts].sort((a, b) => Number(a) - Number(b)).join(', ')}`
  const numbers = parts.filter(isNumber).sort((a, b) => Number(a) - Number(b))
  return [...numbers, ...parts.filter((p) => !isNumber(p))].join(', ')
}

/**
 * Splits a note's links into the rail's groups. Rejected and orphaned links are left out; the same
 * entity linked at several anchors counts once.
 * @param {import('../api/types.js').NoteLink[]} links
 * @param {typeof DEFAULT_ENTITY_GROUPS} [groups]
 */
export function groupLinks(links, groups = DEFAULT_ENTITY_GROUPS) {
  const live = (links ?? []).filter((l) => (l.status ?? 'confirmed') === 'confirmed')
  const seen = new Set()
  const unique = live.filter((l) => {
    if (l.entity_type == null || l.entity_id == null) return false
    const key = `${l.entity_type}/${l.entity_id}`
    if (seen.has(key)) return false
    seen.add(key)
    return true
  })

  const works = new Map()
  const composers = []
  const other = []
  const group = (label) => {
    if (!works.has(label)) works.set(label, { label, entity: null, parts: [], firstPart: null })
    return works.get(label)
  }
  for (const link of unique) {
    const label = link.entity_label ?? ''
    if (groups.works.includes(link.entity_type)) {
      group(label.split(SEPARATOR)[0]).entity ??= link
    } else if (groups.parts.includes(link.entity_type)) {
      const i = label.indexOf(SEPARATOR)
      const g = group(i > 0 ? label.slice(0, i) : label)
      if (i > 0) g.parts.push(partText(label.slice(i + SEPARATOR.length)))
      g.firstPart ??= link
    } else if (groups.composers.includes(link.entity_type)) {
      composers.push(link)
    } else {
      other.push(link)
    }
  }
  const actions = (links ?? []).filter((l) => l.action_item && (l.status ?? 'confirmed') !== 'rejected')
  return { works: [...works.values()], composers, other, actions }
}

function formatValue(value, strings) {
  if (value == null || value === '') return strings.noValue
  if (Array.isArray(value)) return value.length ? value.map((v) => formatValue(v, strings)).join(', ') : strings.noValue
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}

/** Frontmatter rows for the Properties card. The sync identity key is plumbing, not a property. */
export function propertyRows(frontmatter, strings = withStrings()) {
  return Object.entries(frontmatter ?? {})
    .filter(([key]) => key !== 'arp_id')
    .map(([key, value]) => [key.replace(/_/g, ' '), formatValue(value, strings)])
}

function Section({ title, children, label }) {
  return (
    <section style={{ ...styles.card, padding: 16, display: 'flex', flexDirection: 'column', gap: 8 }} aria-label={label} data-rail-section={label}>
      <h2 style={{ ...styles.sectionHeading, marginBottom: 0 }}>{title}</h2>
      {children}
    </section>
  )
}

function Images({ images, strings, onAttachmentExpired }) {
  const [all, setAll] = useState(false)
  const shown = all ? images : images.slice(0, IMAGE_GRID_LIMIT)
  const rest = images.length - shown.length
  const total = images.reduce((sum, a) => sum + (a.size_bytes ?? 0), 0)
  return (
    <>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, minmax(0, 1fr))', gap: 6 }} data-rail-images="">
        {shown.map((a) => (
          <a key={a.id ?? a.sha256} href={a.content_url} aria-label={strings.openImage(a.filename)} style={{ display: 'block' }}>
            <img
              src={a.content_url}
              alt={strings.imageAlt(a.filename)}
              loading="lazy"
              onError={onAttachmentExpired}
              style={{ ...styles.shot, width: '100%', height: 40 }}
            />
          </a>
        ))}
        {rest > 0 ? (
          <button
            type="button"
            onClick={() => setAll(true)}
            aria-label={strings.showMoreImages(rest)}
            style={{
              ...styles.shot,
              backgroundImage: 'none',
              height: 40,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              fontFamily: 'inherit',
              fontSize: 12,
              fontWeight: 600,
              color: 'var(--arpn-fg2)',
              cursor: 'pointer',
              padding: 0,
            }}
            data-more-images=""
          >
            +{rest}
          </button>
        ) : null}
      </div>
      <div style={{ ...styles.muted, fontSize: 12 }}>{strings.imagesNote(formatBytes(total))}</div>
    </>
  )
}

/**
 * @param {Object} props
 * @param {import('../api/types.js').Note} props.note
 * @param {(entityType: string, entityId: number) => string|undefined} [props.hrefForEntity]
 * @param {(link: import('../api/types.js').NoteLink) => string|null|undefined} [props.laneFor]  Lane badge for an action item
 *   ('practice' | 'lesson'). Default: `link.lane`, which hosts may add to the links they return. No lane, no badge.
 * @param {() => void} [props.onAttachmentExpired]  An image failed to load (its signed URL expired, K§8): re-fetch the note.
 * @param {typeof DEFAULT_ENTITY_GROUPS} [props.entityGroups]
 * @param {Partial<import('./strings.js').STRINGS>} [props.strings]
 */
export function NoteRail({ note, hrefForEntity, laneFor, onAttachmentExpired, entityGroups = DEFAULT_ENTITY_GROUPS, strings: stringOverrides }) {
  const strings = useMemo(() => withStrings(stringOverrides), [stringOverrides])
  const grouped = useMemo(() => groupLinks(note.links, entityGroups), [note.links, entityGroups])
  const images = useMemo(() => (note.attachments ?? []).filter((a) => a.mime?.startsWith('image/') && a.content_url), [note.attachments])
  const props = useMemo(() => propertyRows(note.frontmatter, strings), [note.frontmatter, strings])
  const { works, composers, other, actions } = grouped
  if (!works.length && !composers.length && !other.length && !actions.length && !images.length && !props.length) return null

  return (
    <aside aria-label={strings.railLabel} style={{ ...styles.root, width: '100%', display: 'flex', flexDirection: 'column', gap: 16 }} data-note-rail="">
      {works.length ? (
        <Section title={strings.linkedPieces(works.length)} label="pieces">
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            {works.map((w) => {
              const target = w.entity ?? w.firstPart
              const summary = partsSummary(w.parts, strings.partPrefix)
              return (
                <div key={w.label}>
                  <EntityChip entityType={target?.entity_type} entityId={target?.entity_id} label={w.label} hrefForEntity={hrefForEntity} />
                  {summary ? <div style={{ ...styles.muted, fontSize: 13, marginTop: 4 }}>{summary}</div> : null}
                </div>
              )
            })}
          </div>
        </Section>
      ) : null}

      {composers.length ? (
        <Section title={strings.composers(composers.length)} label="composers">
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
            {composers.map((l) => (
              <EntityChip key={l.entity_id} entityType={l.entity_type} entityId={l.entity_id} label={l.entity_label} hrefForEntity={hrefForEntity} />
            ))}
          </div>
        </Section>
      ) : null}

      {other.length ? (
        <Section title={strings.otherLinks(other.length)} label="other">
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
            {other.map((l) => (
              <EntityChip key={`${l.entity_type}/${l.entity_id}`} entityType={l.entity_type} entityId={l.entity_id} label={l.entity_label} hrefForEntity={hrefForEntity} />
            ))}
          </div>
        </Section>
      ) : null}

      {actions.length ? (
        <Section title={strings.actionItems(actions.length)} label="actions">
          <ul style={{ margin: 0, padding: 0, listStyle: 'none', display: 'flex', flexDirection: 'column', gap: 8 }}>
            {actions.map((l) => {
              const lane = laneFor ? laneFor(l) : l.lane
              const done = Boolean(l.action_completed)
              return (
                <li key={l.id ?? l.action_item} style={{ fontSize: 14 }} data-action="">
                  <span style={done ? { textDecoration: 'line-through' } : undefined}>{l.action_item}</span>{' '}
                  {lane ? <span style={styles.badge('neu')}>{strings.laneLabels[lane] ?? kindLabel(lane)}</span> : null}
                  {done ? <span style={{ ...styles.badge('app'), marginLeft: 4 }}>{strings.done}</span> : null}
                </li>
              )
            })}
          </ul>
        </Section>
      ) : null}

      {images.length ? (
        <Section title={strings.imagesHeading(images.length)} label="images">
          <Images images={images} strings={strings} onAttachmentExpired={onAttachmentExpired} />
        </Section>
      ) : null}

      {props.length ? (
        <Section title={strings.properties} label="properties">
          <dl style={{ display: 'grid', gridTemplateColumns: '110px minmax(0, 1fr)', gap: '4px 8px', margin: 0, fontSize: 13 }}>
            {props.map(([key, value]) => (
              <div key={key} style={{ display: 'contents' }}>
                <dt style={styles.muted}>{key}</dt>
                <dd style={{ margin: 0, overflowWrap: 'anywhere' }}>{value}</dd>
              </div>
            ))}
          </dl>
        </Section>
      ) : null}
    </aside>
  )
}
