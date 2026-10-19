// remarkChips: '[@Title](prefix://entity_type/id)' (and PT's legacy 'mention://type/slug') -> <arpn-chip>.
// Web links (http, https, mailto, tel) stay links. The label is kept as written, '@' included.
import { walk } from './tree.js'

const CUSTOM = /^([a-z][a-z0-9+.-]*):\/\/([^/?#]+)\/([^?#]+)$/i
const WEB = new Set(['http', 'https', 'mailto', 'tel', 'ftp'])

export function parseChipUrl(url) {
  const m = CUSTOM.exec(url ?? '')
  if (!m || WEB.has(m[1].toLowerCase())) return null
  let id = m[3]
  try {
    id = decodeURIComponent(id)
  } catch {
    /* keep the raw segment */
  }
  return { prefix: m[1].toLowerCase(), entityType: decodeURIComponentSafe(m[2]), entityId: id }
}

function decodeURIComponentSafe(value) {
  try {
    return decodeURIComponent(value)
  } catch {
    return value
  }
}

export function remarkChips() {
  return (tree) => {
    walk(tree, (node, parent, index) => {
      if (node.type !== 'link' || !parent) return
      const chip = parseChipUrl(node.url)
      if (!chip) return
      parent.children[index] = {
        type: 'arpnChip',
        data: {
          hName: 'arpn-chip',
          hProperties: {
            'data-prefix': chip.prefix,
            'data-entity-type': chip.entityType,
            'data-entity-id': chip.entityId,
          },
        },
        children: node.children,
      }
      return false
    })
  }
}
