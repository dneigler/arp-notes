// C6a scenes: NoteBody on a Howat-style masterclass note and on the synthetic Obsidian corpus (spike
// §4.1). 'body-corpus-open' opens every Show source toggle, so axe also sees the expanded state, and
// 'body-phone' is the same note in a 390 px column.
import { createElement as h } from 'react'
import { flushSync } from 'react-dom'
import { createRoot } from 'react-dom/client'
import { NoteBody } from '../../src/body/index.js'
import corpus from '../../test/fixtures/obsidian-synthetic.md?raw'

function shot(label, bg) {
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="600" height="360"><rect width="600" height="360" fill="${bg}"/><text x="300" y="190" text-anchor="middle" font-family="sans-serif" font-size="28" fill="#111">${label}</text></svg>`
  return `data:image/svg+xml;utf8,${encodeURIComponent(svg)}`
}

const attachment = (id, ref, filename, bg) => ({
  id,
  blob_id: id,
  filename,
  ref_in_markdown: ref,
  mime: 'image/svg+xml',
  size_bytes: 1200,
  sha256: String(id).repeat(64).slice(0, 64),
  content_url: shot(filename, bg),
})

const howat = {
  body_md: [
    '---',
    'arp_id: 5b2f6c1e',
    'duration: 25',
    '---',
    '# Op. 10 no. 3',
    '',
    '**Attendees**:: [[A. Presenter]]',
    '**Place**:: Studio B',
    '',
    'Keep the melody singing and the left hand quiet. Compare [@Études, Op.10](pt://repertoire/35) with [@Preludes](pt://repertoire/99).',
    '',
    '![[2026-10-18 masterclass-1.webp]]',
    '',
    '## Pedalling',
    '',
    '- [ ] Try half pedal at the **climax** of the middle section',
    '- Ask about the [[Chopin Études Op. 10]] fingering ![[missing-photo.png]]',
    '',
    '| Bar | Idea |',
    '|---:|:---|',
    '| 27 | compare WTC I |',
    '',
    '```dataview',
    'TABLE meeting-date FROM #MeetingNote',
    '```',
    '',
    'Also see [@Études, Op.25](pt://repertoire/36) and an old [@mention](mention://repertoire/etudes).',
  ].join('\n'),
  attachments: [attachment(1, '![[2026-10-18 masterclass-1.webp]]', '2026-10-18 masterclass-1.webp', '#BAE6FD')],
  links: [
    {
      id: 1,
      entity_type: 'repertoire',
      entity_id: 35,
      entity_label: 'Études, Op. 10',
      anchor: 'op-10-no-3',
      quote: 'Keep the melody singing and the left hand quiet.',
      action_completed: 0,
      status: 'confirmed',
      sort_order: 0,
    },
    {
      id: 2,
      entity_type: 'repertoire',
      entity_id: 35,
      entity_label: 'Études, Op. 10',
      anchor: 'pedalling',
      quote: 'half pedal',
      backlog_id: 12,
      action_completed: 0,
      status: 'confirmed',
      sort_order: 1,
    },
  ],
}

const schemes = [{ prefix: 'pt', entity_types: ['repertoire', 'composer'] }]
const hrefForEntity = (type, id) => (type === 'repertoire' && id !== 99 ? `#/body?entity=${type}-${id}` : null)

function mountBody(container, props, { width, open } = {}) {
  const host = document.createElement('div')
  if (width) host.style.cssText = `width:${width}px;max-width:100%`
  container.append(host)
  const root = createRoot(host)
  flushSync(() => root.render(h(NoteBody, { schemes, hrefForEntity, ...props })))
  if (open) {
    flushSync(() => {
      for (const button of host.querySelectorAll('[data-dataview] button')) button.click()
    })
  }
}

const pending = [{ quote: 'fingering', anchor: 'pedalling' }]

export default [
  {
    id: 'body',
    title: 'Note body',
    render: (c) => mountBody(c, { note: howat, pending }),
  },
  {
    id: 'body-phone',
    title: 'Note body (phone)',
    render: (c) => mountBody(c, { note: howat, pending }, { width: 390 }),
  },
  {
    id: 'body-corpus',
    title: 'Obsidian corpus',
    render: (c) => mountBody(c, { note: { body_md: corpus, attachments: [] } }),
  },
  {
    id: 'body-corpus-open',
    title: 'Obsidian corpus (source open)',
    render: (c) => mountBody(c, { note: { body_md: corpus, attachments: [] } }, { open: true }),
  },
  {
    id: 'body-howat-open',
    title: 'Note body (source open)',
    render: (c) => mountBody(c, { note: howat, pending }, { open: true }),
  },
]
