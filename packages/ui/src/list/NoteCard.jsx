// NoteCard: a note as a card on the host's Day page, Dashboard "Today" strip or an activity feed.
// Variants follow the DayDesk / DayPhone / TodayDesk artboards. It never fetches: the summary, the
// excerpt and the images come in as props, and routes are the host's (hrefForNote, hrefForEntity).
import { useMemo } from 'react'
import { DocIcon } from './icons.jsx'
import { durationMinutes, formatClock, kindLabel } from './format.js'
import { useIsPhone } from './hooks.js'
import { EntityChip, OriginBadge, ReviewBadge, activityLabel, originKind } from './parts.jsx'
import { styles } from './styles.js'
import { withStrings } from './strings.js'

export const NOTE_CARD_VARIANTS = ['day', 'today', 'feed']

/** Accepts Attachment rows ({content_url, filename}) or plain {url, filename, alt}. */
function normalizeImages(images) {
  return (images ?? [])
    .map((img) => ({ url: img.url ?? img.content_url, filename: img.filename ?? '', alt: img.alt }))
    .filter((img) => img.url)
}

function Thumbs({ images, total, shown, columns, gap, height, radius, href, strings, onAttachmentExpired, phone }) {
  const visible = images.slice(0, shown)
  const rest = Math.max(0, total - visible.length)
  if (!visible.length) return null
  return (
    <div style={{ display: 'grid', gridTemplateColumns: `repeat(${columns}, minmax(0, 1fr))`, gap }} data-images="">
      {visible.map((img, i) => (
        <img
          key={`${img.url}-${i}`}
          src={img.url}
          alt={img.alt ?? strings.imageAlt(img.filename)}
          loading="lazy"
          onError={onAttachmentExpired}
          style={{ ...styles.shot, width: '100%', height, borderRadius: radius }}
        />
      ))}
      {rest > 0 ? (
        <MoreTile href={href} height={height} radius={radius} text={phone ? `+${rest}` : strings.moreImages(rest)} />
      ) : null}
    </div>
  )
}

function MoreTile({ href, height, radius, text }) {
  const box = {
    height,
    borderRadius: radius,
    boxSizing: 'border-box',
    border: '1px solid var(--arpn-border)',
    background: 'var(--arpn-surface)',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    fontWeight: 600,
    fontSize: 13,
    color: 'var(--arpn-fg2)',
    textDecoration: 'none',
  }
  return href ? (
    <a href={href} style={box} data-more-images="">
      {text}
    </a>
  ) : (
    <span style={box} data-more-images="">
      {text}
    </span>
  )
}

function Chips({ summary, limit, phone, strings, hrefForEntity }) {
  const top = (summary.top_links ?? []).slice(0, limit)
  const extra = Math.max(0, (summary.link_count ?? 0) - top.length)
  if (!top.length && !extra) return null
  return (
    <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center' }}>
      {top.map((l) => (
        <EntityChip key={`${l.entity_type}/${l.entity_id}`} entityType={l.entity_type} entityId={l.entity_id} label={l.entity_label} hrefForEntity={hrefForEntity} />
      ))}
      {extra ? <span style={{ ...styles.muted, fontSize: 13 }}>{phone ? `+${extra}` : strings.moreCount(extra)}</span> : null}
    </div>
  )
}

function metaText(summary, strings, phone) {
  const parts = [kindLabel(summary.kind)]
  if (summary.person) parts.push(phone ? summary.person : strings.withPerson(summary.person))
  const minutes = durationMinutes(summary)
  if (minutes != null) parts.push(strings.minutes(minutes))
  return parts.filter(Boolean).join(' · ')
}

function Tile({ size = 40, radius = 12, children }) {
  return (
    <div style={styles.tile(size, radius)} aria-hidden="true">
      {children ?? <DocIcon size={Math.round(size * 0.5)} />}
    </div>
  )
}

function TitleLink({ summary, href, size }) {
  return (
    <h3 style={{ margin: 0, fontSize: size, fontWeight: 600, overflowWrap: 'anywhere' }}>
      {href ? (
        <a href={href} style={{ color: 'var(--arpn-fg)', textDecoration: 'none' }}>
          {summary.title}
        </a>
      ) : (
        summary.title
      )}
    </h3>
  )
}

/** The Dashboard "Today" strip. Wide: image mosaic beside the text. Narrow: a compact tile card. */
function TodayCard({ rootRef, summary, images, total, href, hrefForEntity, strings, onAttachmentExpired, phone, rootProps }) {
  const labels = (summary.top_links ?? []).map((l) => l.entity_label)
  const n = summary.review_pending ?? 0
  const cardStyle = { ...styles.card, display: 'flex', textDecoration: 'none', color: 'var(--arpn-fg)', borderColor: 'var(--arpn-chip-bd)' }
  const Wrapper = href ? 'a' : 'div'
  const wrapperProps = href ? { href } : {}
  const badges = (
    <span style={{ display: 'flex', gap: 6, flexWrap: 'wrap', alignSelf: 'flex-start' }}>
      {phone ? null : <OriginBadge note={summary} strings={strings} short />}
      {n > 0 ? <span style={styles.badge('amb')} data-review-badge="">{strings.suggestionsToReview(n)}</span> : null}
    </span>
  )
  if (phone) {
    const topNames = labels.slice(0, 2)
    const more = Math.max(0, (summary.link_count ?? 0) - topNames.length)
    const sub = [total ? strings.images(total) : '', topNames.length ? `${topNames.join(', ')}${more ? ` +${more}` : ''}` : '']
      .filter(Boolean)
      .join(' · ')
    return (
      <article ref={rootRef} {...rootProps}>
        <Wrapper {...wrapperProps} style={{ ...cardStyle, flexDirection: 'column', gap: 6, padding: 14 }}>
          <span style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
            <Tile size={28} radius={10} />
            <span style={{ ...styles.muted, fontSize: 12, fontWeight: 700, letterSpacing: '.04em', textTransform: 'uppercase' }}>{kindLabel(summary.kind)}</span>
          </span>
          <span style={{ fontWeight: 600, fontSize: 15 }}>{summary.title}</span>
          {sub ? <span style={{ ...styles.muted, fontSize: 13 }}>{sub}</span> : null}
          {n > 0 ? badges : null}
        </Wrapper>
      </article>
    )
  }
  return (
    <article ref={rootRef} {...rootProps}>
      <Wrapper {...wrapperProps} style={{ ...cardStyle, flexDirection: 'row', gap: 14, alignItems: 'center', padding: 16 }}>
        {images.length ? (
          <div style={{ width: 120, flex: 'none' }}>
            <Thumbs images={images} total={total} shown={3} columns={2} gap={4} height={44} radius={6} strings={strings} onAttachmentExpired={onAttachmentExpired} phone />
          </div>
        ) : null}
        <span style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column', gap: 4 }}>
          <span style={{ ...styles.muted, fontSize: 12, fontWeight: 700, letterSpacing: '.04em', textTransform: 'uppercase' }}>{strings.noteKindSuffix(kindLabel(summary.kind))}</span>
          <span style={{ fontSize: 16, fontWeight: 600, overflowWrap: 'anywhere' }}>{summary.title}</span>
          {labels.length ? <span style={{ ...styles.muted, fontSize: 13 }}>{labels.slice(0, 3).join(' · ')}</span> : null}
          {badges}
        </span>
      </Wrapper>
    </article>
  )
}

/**
 * @param {Object} props
 * @param {import('../api/types.js').NoteSummary} props.summary
 * @param {string} [props.excerpt]  A short plain-text excerpt (the host cuts it; the card does not parse Markdown).
 * @param {Array<{content_url?: string, url?: string, filename?: string, alt?: string}>} [props.images]  Signed image URLs, first ones shown.
 * @param {number} [props.imageCount]  Total images when more than `images` are passed; default summary.attachment_count.
 * @param {'day'|'today'|'feed'} [props.variant]
 * @param {(id: number, anchor?: string) => string|undefined} [props.hrefForNote]
 * @param {(entityType: string, entityId: number) => string|undefined} [props.hrefForEntity]  Makes the link chips anchors.
 * @param {import('react').ReactNode} [props.footer]  Replaces the default footer line ('Synced 11:05 · 3 action items added to backlog').
 * @param {(summary: import('../api/types.js').NoteSummary) => void} [props.onReview]  Makes the 'N to review' badge a button.
 * @param {() => void} [props.onAttachmentExpired]  An image failed to load (its signed URL expired, K§8): re-fetch the note.
 * @param {'auto'|'desktop'|'phone'} [props.layout]
 * @param {number} [props.now]  Epoch ms for relative times (tests).
 * @param {string} [props.timeZone]  IANA zone for clock times; default the viewer's.
 * @param {Partial<import('./strings.js').STRINGS>} [props.strings]
 */
export function NoteCard({
  summary,
  excerpt,
  images,
  imageCount,
  variant = 'day',
  hrefForNote,
  hrefForEntity,
  footer,
  onReview,
  onAttachmentExpired,
  layout = 'auto',
  now,
  timeZone,
  strings: stringOverrides,
}) {
  const strings = useMemo(() => withStrings(stringOverrides), [stringOverrides])
  const [ref, phone] = useIsPhone(layout)
  const list = useMemo(() => normalizeImages(images), [images])
  const total = Math.max(imageCount ?? summary.attachment_count ?? 0, list.length)
  const href = hrefForNote ? hrefForNote(summary.id) : undefined
  const rootProps = { 'data-note-card': variant, 'data-layout': phone ? 'phone' : 'desktop', 'data-note-id': summary.id }

  if (variant === 'today') {
    return (
      <TodayCard
        rootRef={ref}
        summary={summary}
        images={list}
        total={total}
        href={href}
        hrefForEntity={hrefForEntity}
        strings={strings}
        onAttachmentExpired={onAttachmentExpired}
        phone={phone}
        rootProps={rootProps}
      />
    )
  }

  const feed = variant === 'feed'
  const origin = originKind(summary)
  const clock = formatClock(origin === 'source' ? summary.last_synced_at ?? summary.updated_at : origin === 'llm' ? summary.created_at ?? summary.updated_at : summary.updated_at, timeZone)
  const whenWord = origin === 'source' ? strings.synced : origin === 'llm' ? strings.created : strings.edited
  const footerText = footer ?? strings.dayFooter(clock ? whenWord(clock) : '', summary.action_count ?? 0)
  const reviewBadge = (
    <ReviewBadge note={summary} strings={strings} onReview={onReview} href={onReview ? undefined : href} />
  )

  return (
    <article ref={ref} style={{ ...styles.root, ...styles.card, padding: phone ? 14 : 18, display: 'flex', flexDirection: 'column', gap: phone ? 10 : 12 }} {...rootProps}>
      <div style={{ display: 'flex', gap: phone ? 10 : 12, alignItems: 'flex-start' }}>
        <Tile size={phone ? 36 : 40} />
        <div style={{ flex: 1, minWidth: 0 }}>
          <TitleLink summary={summary} href={href} size={phone ? 16 : 17} />
          <div style={{ ...styles.muted, fontSize: 13, display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
            {metaText(summary, strings, phone)}
            {phone ? null : <OriginBadge note={summary} strings={strings} short />}
          </div>
        </div>
        {phone ? null : reviewBadge}
        {feed && !phone ? (
          <span style={{ ...styles.muted, fontSize: 13, whiteSpace: 'nowrap' }} data-activity={origin}>
            {activityLabel(summary, strings, now ?? Date.now())}
          </span>
        ) : null}
      </div>

      {excerpt ? (
        <p
          style={{
            margin: 0,
            fontSize: phone ? 14 : 15,
            lineHeight: 1.6,
            color: 'var(--arpn-fg2)',
            ...(feed ? { display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical', overflow: 'hidden' } : null),
          }}
          data-excerpt=""
        >
          {excerpt}
        </p>
      ) : null}

      {feed ? null : (
        <Thumbs
          images={list}
          total={total}
          shown={phone ? 3 : 4}
          columns={phone ? 4 : 5}
          gap={phone ? 6 : 8}
          height={phone ? 56 : 76}
          radius={8}
          href={href}
          strings={strings}
          onAttachmentExpired={onAttachmentExpired}
          phone={phone}
        />
      )}

      <Chips summary={summary} limit={phone ? 2 : 4} phone={phone} strings={strings} hrefForEntity={hrefForEntity} />

      {phone ? (
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          <OriginBadge note={summary} strings={strings} short />
          {reviewBadge}
          <span style={{ flex: 1 }} />
          {href ? (
            <a href={href} style={{ ...styles.link, fontWeight: 600, fontSize: 14, minHeight: 44, display: 'inline-flex', alignItems: 'center' }}>
              {strings.openShort}
            </a>
          ) : null}
        </div>
      ) : feed && !footer ? null : (
        <div style={{ display: 'flex', gap: 12, alignItems: 'center', borderTop: '1px solid var(--arpn-border)', paddingTop: 10, fontSize: 13 }} data-footer="">
          <span style={{ ...styles.muted, flex: 1 }}>{footerText}</span>
          {href ? (
            <a href={href} style={{ ...styles.link, fontWeight: 600, minHeight: 32, display: 'inline-flex', alignItems: 'center' }}>
              {strings.openNote}
            </a>
          ) : null}
        </div>
      )}
    </article>
  )
}
