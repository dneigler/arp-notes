// A small modal confirm, used by NoteDetailHeader for "Delete from <host>…". Focus moves into the
// dialog (onto Cancel, the safe choice), Tab stays inside, Esc and the scrim cancel, the page behind
// does not scroll, and focus returns to what had it. Rendered in place with position: fixed.
import { useEffect, useId, useRef } from 'react'
import { styles } from './styles.js'

const FOCUSABLE = 'button, [href], input, select, textarea, [tabindex]'

function focusables(root) {
  return [...root.querySelectorAll(FOCUSABLE)].filter(
    (el) => !el.disabled && el.tabIndex >= 0 && !el.hidden && el.getAttribute('aria-hidden') !== 'true',
  )
}

function useModal(panelRef, initialRef, onEscape) {
  const escape = useRef(onEscape)
  escape.current = onEscape
  useEffect(() => {
    const panel = panelRef.current
    const previous = document.activeElement
    const overflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    ;(initialRef.current ?? panel).focus()

    const onKeyDown = (e) => {
      if (e.key === 'Escape') {
        e.preventDefault()
        e.stopPropagation()
        escape.current()
        return
      }
      if (e.key !== 'Tab') return
      const items = focusables(panel)
      if (!items.length) {
        e.preventDefault()
        panel.focus()
        return
      }
      const first = items[0]
      const last = items[items.length - 1]
      const active = document.activeElement
      if (!panel.contains(active) || active === panel) {
        e.preventDefault()
        ;(e.shiftKey ? last : first).focus()
      } else if (e.shiftKey && active === first) {
        e.preventDefault()
        last.focus()
      } else if (!e.shiftKey && active === last) {
        e.preventDefault()
        first.focus()
      }
    }
    const onFocusIn = (e) => {
      if (!panel.contains(e.target)) (focusables(panel)[0] ?? panel).focus()
    }
    document.addEventListener('keydown', onKeyDown, true)
    document.addEventListener('focusin', onFocusIn)
    return () => {
      document.removeEventListener('keydown', onKeyDown, true)
      document.removeEventListener('focusin', onFocusIn)
      document.body.style.overflow = overflow
      if (previous && typeof previous.focus === 'function') previous.focus()
    }
  }, [panelRef, initialRef])
}

/**
 * @param {Object} props
 * @param {string} props.title
 * @param {string} props.body
 * @param {string} props.confirmLabel
 * @param {string} props.cancelLabel
 * @param {() => void} props.onConfirm
 * @param {() => void} props.onCancel
 * @param {boolean} [props.busy]   Disables both buttons while the host works.
 * @param {string} [props.error]   Shown in an alert under the body.
 * @param {string} [props.busyLabel]
 */
export function ConfirmDialog({ title, body, confirmLabel, cancelLabel, onConfirm, onCancel, busy = false, error = '', busyLabel = '' }) {
  const panel = useRef(null)
  const cancel = useRef(null)
  const titleId = useId()
  const bodyId = useId()
  useModal(panel, cancel, () => {
    if (!busy) onCancel()
  })
  return (
    <div
      style={{ position: 'fixed', inset: 0, zIndex: 50, background: 'var(--arpn-scrim)', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 16, boxSizing: 'border-box' }}
      onMouseDown={(e) => {
        if (e.target === e.currentTarget && !busy) onCancel()
      }}
      data-confirm-dialog=""
    >
      <div
        ref={panel}
        role="alertdialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={bodyId}
        tabIndex={-1}
        style={{
          ...styles.root,
          width: '100%',
          maxWidth: 440,
          maxHeight: '100%',
          overflowY: 'auto',
          boxSizing: 'border-box',
          background: 'var(--arpn-raised)',
          border: '1px solid var(--arpn-border2)',
          borderRadius: 16,
          boxShadow: 'var(--arpn-shadow)',
          padding: 20,
          display: 'flex',
          flexDirection: 'column',
          gap: 12,
          outline: 'none',
        }}
      >
        <h2 id={titleId} style={{ margin: 0, fontSize: 18, fontWeight: 700 }}>
          {title}
        </h2>
        <p id={bodyId} style={{ margin: 0, fontSize: 14, color: 'var(--arpn-fg2)' }}>
          {body}
        </p>
        {error ? (
          <div role="alert" style={{ borderRadius: 12, padding: '10px 12px', background: 'var(--arpn-del-bg)', color: 'var(--arpn-del-fg)', fontSize: 14 }}>
            {error}
          </div>
        ) : null}
        <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end', flexWrap: 'wrap' }}>
          <button ref={cancel} type="button" style={styles.button} onClick={onCancel} disabled={busy}>
            {cancelLabel}
          </button>
          <button type="button" style={{ ...styles.button, ...styles.buttonDanger }} onClick={onConfirm} disabled={busy}>
            {busy ? busyLabel || confirmLabel : confirmLabel}
          </button>
        </div>
      </div>
    </div>
  )
}
