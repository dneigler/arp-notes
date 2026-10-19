// Upload progress text: '62% · 1.8 of 2.9 MB' (EditorDesk upload row).

const MIB = 1024 * 1024
const KIB = 1024

/** `{loaded, total}` in bytes -> '62% · 1.8 of 2.9 MB'. Sizes under 1 MB read in KB. Unknown total -> just the loaded size. */
export function formatUploadProgress({ loaded, total }) {
  const unit = (total || loaded) < MIB ? { size: KIB, label: 'KB', digits: 0 } : { size: MIB, label: 'MB', digits: 1 }
  const fmt = (n) => (n / unit.size).toFixed(unit.digits)
  if (!total) return `${fmt(loaded)} ${unit.label}`
  const pct = Math.min(100, Math.floor((loaded / total) * 100))
  return `${pct}% · ${fmt(loaded)} of ${fmt(total)} ${unit.label}`
}
