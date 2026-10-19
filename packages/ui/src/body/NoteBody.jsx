// NoteBody: renders a note's Markdown with the Obsidian constructs, host link chips, signed images
// and link highlighting. It never mutates body_md and never fetches.
import { useCallback, useId, useMemo, useRef, useState } from 'react'
import Markdown, { defaultUrlTransform } from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { blankFrontmatter } from './frontmatter.js'
import { remarkChips } from './remarkChips.js'
import { remarkLinkHighlights } from './remarkHighlights.js'
import { remarkObsidianLite } from './remarkObsidianLite.js'
import { scanHeadings } from './anchors.js'
import { styles } from './styles.js'

export const DEFAULT_STRINGS = {
  notFound: 'not found',
  dataviewTitle: 'Obsidian query — not rendered here',
  showSource: 'Show source',
  hideSource: 'Hide source',
  missingImage: 'Image not synced',
  missingFile: 'Attachment not synced',
  missingNote: 'Embedded note',
  taskDone: 'Done',
  taskOpen: 'Not done',
}

// Embeds are built from the host's own attachment records, so their (often data: or signed) URLs
// pass; everything else in the body keeps react-markdown's protocol allow-list.
function urlTransform(url, key, node) {
  const embed = /arpn-embed/.test([].concat(node?.properties?.className ?? []).join(' '))
  if (embed) return /^\s*(?:javascript|vbscript):/i.test(url) ? '' : url
  return defaultUrlTransform(url)
}

// How long after an image error further errors are folded into the same onAttachmentExpired call.
const EXPIRED_COALESCE_MS = 1000

function entityIdFrom(raw) {
  return /^\d+$/.test(raw) ? Number(raw) : raw
}

function Chip({ node: _node, children, schemes, hrefForEntity, strings, ...props }) {
  const prefix = props['data-prefix']
  const type = props['data-entity-type']
  const id = entityIdFrom(props['data-entity-id'] ?? '')
  // 'mention' is PT's legacy chip scheme; it is not advertised in capabilities.schemes.
  const known =
    prefix === 'mention' ||
    !schemes ||
    schemes.some((s) => s.prefix === prefix && (!s.entity_types || s.entity_types.includes(type)))
  const href = known && hrefForEntity ? hrefForEntity(type, id) : null
  if (!href) {
    return (
      <span style={styles.chipMissing} data-chip="missing">
        {children}
        <span> · {strings.notFound}</span>
      </span>
    )
  }
  return (
    <a href={href} style={styles.chip} data-chip="resolved" data-entity-type={type} data-entity-id={String(id)}>
      {children}
    </a>
  )
}

function Dataview({ strings, ...props }) {
  const [open, setOpen] = useState(false)
  const id = useId()
  return (
    <div style={styles.dataview} data-dataview="">
      <div style={styles.dataviewBar}>
        <span>{strings.dataviewTitle}</span>
        <button
          type="button"
          style={styles.dataviewToggle}
          aria-expanded={open}
          aria-controls={id}
          onClick={() => setOpen((v) => !v)}
        >
          {open ? strings.hideSource : strings.showSource}
        </button>
      </div>
      <pre id={id} hidden={!open} style={{ ...styles.pre, margin: '8px 0 0' }}>
        {props['data-source']}
      </pre>
    </div>
  )
}

function MissingEmbed({ node: _node, children, strings, ...props }) {
  const kind = props['data-kind']
  const label = kind === 'image' ? strings.missingImage : kind === 'note' ? strings.missingNote : strings.missingFile
  const size = {}
  if (props.width) size.width = Number(props.width)
  return (
    <span style={{ ...styles.placeholder, ...size }} data-embed-missing={kind} role="img" aria-label={`${label}: ${props['data-name']}`}>
      <span style={styles.placeholderLabel} aria-hidden="true">
        {label}: {children}
      </span>
    </span>
  )
}

/**
 * @param {Object} props
 * @param {import('../api/types.js').Note} props.note
 * @param {import('../api/types.js').NoteLink[]} [props.links]  Defaults to note.links. Only confirmed links with a quote are highlighted.
 * @param {Array<{prefix: string, entity_types?: string[]}>} [props.schemes]  capabilities.schemes; a chip whose scheme is not listed reads '· not found'.
 * @param {(entityType: string, id: number|string) => string|null|undefined} props.hrefForEntity
 * @param {(info: {src: string, filename: string|null}) => void} [props.onAttachmentExpired]  An embedded image failed to load (signed URLs last 1 h); refetch the note.
 * @param {Array<{quote?: string, mention?: string, anchor?: string|null}>} [props.pending]  Ambiguous mentions awaiting a pick; marked 'needs a pick'.
 * @param {Partial<typeof DEFAULT_STRINGS>} [props.strings]
 */
export function NoteBody({ note, links, schemes, hrefForEntity, onAttachmentExpired, pending, strings, className }) {
  const copy = useMemo(() => ({ ...DEFAULT_STRINGS, ...strings }), [strings])
  const uid = useId()
  const lastExpired = useRef(0)
  const body = useMemo(() => blankFrontmatter(note?.body_md ?? ''), [note?.body_md])
  const attachments = note?.attachments
  const useLinks = links ?? note?.links

  const remarkPlugins = useMemo(
    () => [
      remarkGfm,
      [remarkLinkHighlights, { links: useLinks ?? [], pending: pending ?? [] }],
      [remarkObsidianLite, { attachments: attachments ?? [] }],
      remarkChips,
    ],
    [useLinks, pending, attachments],
  )

  const notifyExpired = useCallback(
    (src, filename) => {
      if (!onAttachmentExpired) return
      const now = Date.now()
      if (now - lastExpired.current < EXPIRED_COALESCE_MS) return
      lastExpired.current = now
      onAttachmentExpired({ src, filename })
    },
    [onAttachmentExpired],
  )

  const headingAnchors = useMemo(() => new Map(scanHeadings(body).map((h) => [h.line, h.anchor])), [body])

  const components = useMemo(() => {
    const heading = (level) =>
      function Heading({ node, children, ...rest }) {
        const Tag = `h${level}`
        return (
          <Tag {...rest} style={styles.h(level)} data-anchor={headingAnchors.get(node?.position?.start.line)}>
            {children}
          </Tag>
        )
      }
    return {
      h1: heading(1),
      h2: heading(2),
      h3: heading(3),
      h4: heading(4),
      h5: heading(5),
      h6: heading(6),
      p: ({ node: _n, ...rest }) => <p {...rest} style={styles.p} />,
      ul: ({ node: _n, ...rest }) => <ul {...rest} style={styles.list} />,
      ol: ({ node: _n, ...rest }) => <ol {...rest} style={styles.list} />,
      blockquote: ({ node: _n, ...rest }) => <blockquote {...rest} style={styles.blockquote} />,
      hr: ({ node: _n, ...rest }) => <hr {...rest} style={styles.hr} />,
      a: ({ node: _n, href, ...rest }) => {
        const external = /^https?:/i.test(href ?? '')
        return <a {...rest} href={href} style={styles.a} {...(external ? { rel: 'noopener noreferrer' } : {})} />
      },
      code: ({ node: _n, className: cls, ...rest }) => {
        const inline = !/language-|\n/.test(`${cls ?? ''}${typeof rest.children === 'string' ? rest.children : ''}`)
        const query = /arpn-inline-query/.test(cls ?? '')
        return <code {...rest} className={cls} style={inline ? (query ? styles.inlineQuery : styles.code) : { fontFamily: 'inherit' }} />
      },
      pre: ({ node: _n, ...rest }) => <pre {...rest} style={styles.pre} />,
      table: ({ node: _n, ...rest }) => (
        <div style={styles.tableWrap}>
          <table {...rest} style={styles.table} />
        </div>
      ),
      th: ({ node: _n, ...rest }) => <th {...rest} style={{ ...styles.th, ...rest.style }} />,
      td: ({ node: _n, ...rest }) => <td {...rest} style={{ ...styles.td, ...rest.style }} />,
      input: ({ node: _n, ...rest }) =>
        rest.type === 'checkbox' ? (
          <input {...rest} aria-label={rest.checked ? copy.taskDone : copy.taskOpen} />
        ) : (
          <input {...rest} />
        ),
      img: ({ node: _n, className: cls, ...rest }) => {
        const embed = /arpn-embed/.test(cls ?? '')
        return (
          <img
            {...rest}
            alt={rest.alt ?? ''}
            style={styles.img}
            loading="lazy"
            onError={embed ? () => notifyExpired(rest.src, rest['data-embed'] ?? null) : undefined}
          />
        )
      },
      mark: ({ node: _n, className: cls, ...rest }) => (
        <mark {...rest} className={cls} style={/arpn-pending/.test(cls ?? '') ? styles.pendingQuote : styles.quote} />
      ),
      dl: ({ node: _n, className: cls, ...rest }) => <dl {...rest} className={cls} style={styles.fields} />,
      div: ({ node: _n, className: cls, ...rest }) => (
        <div {...rest} className={cls} style={/arpn-field\b/.test(cls ?? '') ? styles.field : undefined} />
      ),
      dt: ({ node: _n, ...rest }) => <dt {...rest} style={styles.fieldKey} />,
      dd: ({ node: _n, ...rest }) => <dd {...rest} style={styles.fieldValue} />,
      'arpn-wikilink': ({ node: _n, children, ...rest }) => (
        <span style={styles.wikilink} data-wikilink={rest['data-target']} title={rest['data-target']}>
          {children}
        </span>
      ),
      'arpn-chip': (props) => <Chip {...props} schemes={schemes} hrefForEntity={hrefForEntity} strings={copy} />,
      'arpn-marker': ({ node: _n, children, ...rest }) => (
        <span style={styles.marker(rest['data-kind'])} data-marker={rest['data-kind']}>
          {children}
        </span>
      ),
      'arpn-dataview': (props) => <Dataview {...props} strings={copy} />,
      'arpn-embed-missing': (props) => <MissingEmbed {...props} strings={copy} />,
    }
  }, [headingAnchors, copy, schemes, hrefForEntity, notifyExpired])

  return (
    <div className={className} style={styles.root} data-arpn="note-body">
      <Markdown
        remarkPlugins={remarkPlugins}
        components={components}
        urlTransform={urlTransform}
        remarkRehypeOptions={{ clobberPrefix: `arpn${uid.replace(/\W/g, '')}-` }}
      >
        {body}
      </Markdown>
    </div>
  )
}
