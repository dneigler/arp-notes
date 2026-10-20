// Attachment policy, read from GET /notes/capabilities (K§2): whether attachments are accepted at all,
// which MIME types, and the size limit. The editor checks a file here before any upload starts, and the
// rail's footer is worded from the same response. Nothing is hard-coded to one app.

const KIB = 1024
const MIB = 1024 * 1024

/** 26214400 -> '25 MB', 1887437 -> '1.8 MB', 2048 -> '2 KB'. */
export function formatSize(bytes) {
  if (bytes >= MIB) return `${trim(bytes / MIB)} MB`
  return `${Math.max(1, Math.round(bytes / KIB))} KB`
}

function trim(n) {
  return n.toFixed(1).replace(/\.0$/, '')
}

function mimeAllowed(mime, allowlist) {
  if (allowlist == null) return true
  const type = (mime || '').toLowerCase()
  return allowlist.some((pattern) => {
    const p = pattern.toLowerCase()
    return p.endsWith('/*') ? type.startsWith(p.slice(0, -1)) : p === type
  })
}

/** '' for an acceptable file, else {reason: 'type' | 'size'}. Attachments being off is checked by the caller. */
export function checkFile(file, capabilities) {
  if (!mimeAllowed(file.type, capabilities?.mime_allowlist)) return { reason: 'type' }
  const max = capabilities?.limits?.max_attachment_bytes
  if (typeof max === 'number' && file.size > max) return { reason: 'size' }
  return null
}

function joinWords(words) {
  if (words.length <= 1) return words.join('')
  return `${words.slice(0, -1).join(', ')} and ${words[words.length - 1]}`
}

/** ['image/webp', 'image/png', 'application/pdf'] -> 'Images and PDFs'; null -> 'Files'. */
export function allowedLabel(allowlist, strings) {
  if (allowlist == null) return strings.anyFile
  const names = []
  for (const mime of allowlist) {
    const name = strings.mimeNames[mime] ?? (mime.startsWith('image/') ? strings.mimeNames['image/*'] : mime)
    if (!names.includes(name)) names.push(name)
  }
  return joinWords(names)
}

/** 'This app allows Images and PDFs up to 25 MB · export to Markdown on' (EditorDesk rail footer). */
export function policyFooter(capabilities, strings) {
  if (!capabilities) return ''
  const exporting = capabilities.export ? strings.exportOn : strings.exportOff
  if (!capabilities.attachments) return `${strings.policyNone} · ${exporting}`
  const max = capabilities.limits?.max_attachment_bytes
  const what = allowedLabel(capabilities.mime_allowlist, strings)
  return `${strings.policyAllows(what, typeof max === 'number' ? formatSize(max) : '')} · ${exporting}`
}
