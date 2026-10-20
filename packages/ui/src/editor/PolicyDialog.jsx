// 'Image not added' (EditorDesk): the modal shown when a pasted or dropped file is left out, either because
// the host takes no attachments or because the file's type or size is outside what it allows. One [OK].
import { useEffect, useId, useRef } from 'react'
import { allowedLabel, formatSize } from './policy.js'
import { styles as s } from './styles.js'

const FOCUSABLE = 'button, [href], input, select, textarea, [tabindex]'

// Focus moves into the dialog, Tab stays inside, Esc closes, and focus returns to whatever had it.
function useModal(panelRef, onClose) {
  const close = useRef(onClose)
  close.current = onClose
  useEffect(() => {
    const panel = panelRef.current
    const previous = document.activeElement
    const overflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    panel.querySelector('button')?.focus()
    const onKeyDown = (e) => {
      if (e.key === 'Escape') {
        e.preventDefault()
        e.stopPropagation()
        close.current()
      } else if (e.key === 'Tab') {
        const items = [...panel.querySelectorAll(FOCUSABLE)].filter((el) => !el.disabled)
        if (!items.length) return
        const first = items[0]
        const last = items[items.length - 1]
        if (!panel.contains(document.activeElement)) {
          e.preventDefault()
          first.focus()
        } else if (e.shiftKey && document.activeElement === first) {
          e.preventDefault()
          last.focus()
        } else if (!e.shiftKey && document.activeElement === last) {
          e.preventDefault()
          first.focus()
        }
      }
    }
    document.addEventListener('keydown', onKeyDown, true)
    return () => {
      document.removeEventListener('keydown', onKeyDown, true)
      document.body.style.overflow = overflow
      if (previous && typeof previous.focus === 'function' && document.contains(previous)) previous.focus()
    }
  }, [panelRef])
}

export function PolicyDialog({ rejection, capabilities, strings, onClose }) {
  const panel = useRef(null)
  const uid = useId()
  useModal(panel, onClose)

  const { reason, file } = rejection
  const name = file?.name ?? ''
  const image = (file?.type ?? 'image/').startsWith('image/')
  const body =
    reason === 'type'
      ? strings.policyType(name, allowedLabel(capabilities?.mime_allowlist, strings))
      : reason === 'size'
        ? strings.policySize(name, formatSize(file.size), formatSize(capabilities?.limits?.max_attachment_bytes ?? 0))
        : strings.policyOff

  return (
    <div style={s.overlay} data-arpn="editor-policy-overlay">
      <div
        ref={panel}
        role="dialog"
        aria-modal="true"
        aria-labelledby={`${uid}-t`}
        aria-describedby={`${uid}-b`}
        tabIndex={-1}
        style={s.dialog}
        data-arpn="editor-policy"
        data-reason={reason}
      >
        <h2 id={`${uid}-t`} style={s.dialogTitle}>
          {image ? strings.imageNotAdded : strings.fileNotAdded}
        </h2>
        <p id={`${uid}-b`} style={s.dialogBody}>
          {body}
        </p>
        <div style={s.dialogActions}>
          <button type="button" style={s.primary} onClick={onClose}>
            {strings.ok}
          </button>
        </div>
      </div>
    </div>
  )
}
