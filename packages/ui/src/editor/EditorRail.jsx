// EditorRail: the 'In this note' panel beside the editor (EditorDesk). Links · N (with a not-found state),
// Images · N (with upload progress), and a footer worded from the host's capabilities. It reads the same
// scans the editor draws from, so its counts match what is on the page. It never fetches.
import { useEffect, useMemo, useState } from 'react'
import { chipEntry } from './chips.js'
import { formatSize, policyFooter } from './policy.js'
import { attachmentsInBody, chipsInBody } from './scan.js'
import { mergeStrings } from './strings.js'
import { styles as s } from './styles.js'

const NO_ITEMS = []

function uniqueLinks(chips) {
  const seen = new Map()
  for (const chip of chips) {
    const key = `${chip.prefix}://${chip.entityType}/${chip.entityId}`
    if (!seen.has(key)) seen.set(key, { key, ...chip })
  }
  return [...seen.values()]
}

/** Resolve state of every link, through the cache the editor's chips use. */
function useResolved(links) {
  const [, tick] = useState(0)
  useEffect(() => {
    let live = true
    for (const link of links) {
      const entry = chipEntry(link.scheme, link.entityType, link.entityId)
      if (!entry.value) entry.promise.then(() => live && tick((n) => n + 1))
    }
    return () => {
      live = false
    }
  }, [links])
  return (link) => chipEntry(link.scheme, link.entityType, link.entityId).value
}

function LinkItem({ link, resolved, strings, hrefForEntity }) {
  const missing = resolved && !resolved.found
  const text = resolved?.found ? resolved.title || link.label : link.label
  const href = !missing && hrefForEntity ? hrefForEntity(link.entityType, link.entityId) : null
  const Tag = href ? 'a' : 'span'
  return (
    <li style={s.item} data-link={link.key} data-state={!resolved ? 'pending' : missing ? 'missing' : 'found'}>
      <Tag {...(href ? { href } : null)} style={{ ...s.chip, ...(missing ? s.chipMissing : null) }}>
        {text}
      </Tag>
      <span style={s.itemMeta}>
        {missing ? strings.chipNotFound : (strings.entityTypes[link.entityType] ?? link.entityType)}
      </span>
    </li>
  )
}

/**
 * @param {object} props
 * @param {string} props.doc  The note body as it stands in the editor.
 * @param {Array<{blob_id: number, filename: string, size_bytes: number}>} [props.attachments]  Note.attachments, for sizes.
 * @param {Array<object>} [props.uploads]  `status.uploads` from NoteEditor's onStatus.
 * @param {object} [props.capabilities]  GET /notes/capabilities; the footer is worded from it.
 * @param {Array<object>} [props.schemes]  The same schemes NoteEditor gets, to tell found links from missing ones.
 * @param {(entityType: string, id: number|string) => string|null|undefined} [props.hrefForEntity]
 * @param {object} [props.strings]
 */
export function EditorRail({ doc = '', attachments = NO_ITEMS, uploads = NO_ITEMS, capabilities, schemes = NO_ITEMS, hrefForEntity, strings: overrides }) {
  const strings = mergeStrings(overrides)
  const links = useMemo(() => uniqueLinks(chipsInBody(doc, schemes)), [doc, schemes])
  const images = useMemo(() => attachmentsInBody(doc).filter((a) => a.image && !a.pending), [doc])
  const resolvedOf = useResolved(links)
  const sizeOf = (id) => {
    const found = attachments.find((a) => String(a.blob_id) === String(id))
    return found?.size_bytes ? formatSize(found.size_bytes) : ''
  }
  const sending = uploads.filter((u) => u.state === 'uploading')
  const imageCount = images.length + sending.length
  const footer = policyFooter(capabilities, strings)

  return (
    <aside style={s.rail} aria-label={strings.railTitle} data-arpn="editor-rail">
      <h2 style={s.railTitle}>{strings.railTitle}</h2>

      <section style={s.section} aria-labelledby="arpn-rail-links">
        <h3 id="arpn-rail-links" style={s.sectionHead}>
          {strings.links} · {links.length}
        </h3>
        {links.length ? (
          <ul style={s.list}>
            {links.map((link) => (
              <LinkItem key={link.key} link={link} resolved={resolvedOf(link)} strings={strings} hrefForEntity={hrefForEntity} />
            ))}
          </ul>
        ) : (
          <p style={s.empty}>{strings.noLinks}</p>
        )}
      </section>

      <section style={s.section} aria-labelledby="arpn-rail-images">
        <h3 id="arpn-rail-images" style={s.sectionHead}>
          {strings.images} · {imageCount}
        </h3>
        {imageCount ? (
          <ul style={s.list}>
            {sending.map((u) => (
              <li key={u.id} style={s.item} data-image="uploading">
                <span style={s.itemName}>{u.name}</span>
                <span style={s.itemMeta}>
                  {strings.uploadingShort} {Math.round(u.fraction * 100)}%
                </span>
              </li>
            ))}
            {images.map((img) => (
              <li key={`${img.id}-${img.from}`} style={s.item} data-image="done">
                <span style={s.itemName}>{img.name}</span>
                <span style={s.itemMeta}>{sizeOf(img.id)}</span>
              </li>
            ))}
          </ul>
        ) : (
          <p style={s.empty}>{strings.noImages}</p>
        )}
      </section>

      {footer ? (
        <p style={s.footer} data-arpn="policy-footer">
          {footer}
        </p>
      ) : null}
    </aside>
  )
}
