// Tiny mdast helpers; the body plugins avoid a unist-util-* dependency for these few walks.

const OPAQUE = new Set(['code', 'inlineCode', 'html', 'yaml', 'math', 'inlineMath'])

/** Plain text of a node (text and inline code values), in document order. */
export function nodeText(node) {
  if (node.type === 'text' || node.type === 'inlineCode') return node.value
  return (node.children ?? []).map(nodeText).join('')
}

/** Calls fn(node, parent, index) for every node, parents before children. fn returns false to skip a subtree. */
export function walk(node, fn, parent = null, index = 0) {
  if (fn(node, parent, index) === false) return
  const children = node.children
  if (!children) return
  for (let i = 0; i < children.length; i++) walk(children[i], fn, node, i)
}

export const isOpaque = (node) => OPAQUE.has(node.type)

export const text = (value) => ({ type: 'text', value })

/** An mdast node that rehype renders as `<name {...props}>children</name>`. */
export function element(name, props = {}, children = []) {
  return { type: 'arpnElement', data: { hName: name, hProperties: props }, children }
}
