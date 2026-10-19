// Frontmatter is stripped for display only; body_md itself is never touched (A.5).

const BLOCK = /^---[ \t]*\r?\n[\s\S]*?\r?\n(?:---|\.\.\.)[ \t]*(?:\r?\n|$)/

/**
 * Removes a leading YAML frontmatter block but keeps its line count (the block becomes blank lines),
 * so line numbers in what is rendered still match body_md and anchor scans stay valid.
 */
export function blankFrontmatter(markdown) {
  const m = BLOCK.exec(markdown)
  if (!m) return markdown
  const lines = m[0].split('\n').length - 1
  return '\n'.repeat(lines) + markdown.slice(m[0].length)
}
