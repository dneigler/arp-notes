// EditorToolbar: H / B / I / list / Link [[ / Image above the editor (EditorDesk), or pinned above the
// on-screen keyboard with 'Hide keyboard' (EditorPhone). Every button inserts plain Markdown into the editor
// it is given; none of them changes how the note is stored. A tap never steals focus from the editor, so the
// caret, the selection and the keyboard stay where they were.
import { useEffect, useRef, useState } from 'react'
import { addImageFiles, insertWikiLink, toggleBold, toggleBulletList, toggleHeading, toggleItalic } from './commands.js'
import { ModeToggle } from './ModeToggle.jsx'
import { mergePreviewStrings } from './strings.js'
import { styles as s } from './styles.js'
import { useKeyboardHeight } from './useKeyboardHeight.js'

const PHONE_QUERY = '(max-width: 599px)'

function useIsPhone(variant) {
  const [phone, setPhone] = useState(() => (variant === 'auto' && typeof matchMedia === 'function' ? matchMedia(PHONE_QUERY).matches : false))
  useEffect(() => {
    if (variant !== 'auto' || typeof matchMedia !== 'function') return undefined
    const query = matchMedia(PHONE_QUERY)
    const update = () => setPhone(query.matches)
    update()
    query.addEventListener?.('change', update)
    return () => query.removeEventListener?.('change', update)
  }, [variant])
  return variant === 'phone' || phone
}

/**
 * True while the editor, or the bar element `root`, has focus. Focus moving between the two is not the
 * keyboard going away.
 */
function useEditorFocus(view, root) {
  const [focused, setFocused] = useState(() => Boolean(view?.hasFocus))
  useEffect(() => {
    if (!view) {
      setFocused(false)
      return undefined
    }
    const inside = (node) => Boolean(node) && (view.dom.contains(node) || Boolean(root?.contains(node)))
    const on = () => setFocused(true)
    const off = (event) => {
      if (!inside(event.relatedTarget)) setFocused(false)
    }
    view.dom.addEventListener('focusin', on)
    view.dom.addEventListener('focusout', off)
    root?.addEventListener('focusout', off)
    setFocused(view.hasFocus || inside(document.activeElement))
    return () => {
      view.dom.removeEventListener('focusin', on)
      view.dom.removeEventListener('focusout', off)
      root?.removeEventListener('focusout', off)
    }
  }, [view, root])
  return focused
}

const svgProps = { viewBox: '0 0 18 18', fill: 'none', stroke: 'currentColor', strokeWidth: 1.8, strokeLinecap: 'round', 'aria-hidden': true, focusable: false, style: s.icon }

const ListIcon = () => (
  <svg {...svgProps}>
    <circle cx="3" cy="4.5" r="1" fill="currentColor" />
    <circle cx="3" cy="9" r="1" fill="currentColor" />
    <circle cx="3" cy="13.5" r="1" fill="currentColor" />
    <path d="M7 4.5h9M7 9h9M7 13.5h9" />
  </svg>
)

const ImageIcon = () => (
  <svg {...svgProps}>
    <rect x="2" y="3" width="14" height="12" rx="2" />
    <circle cx="6.5" cy="7.2" r="1.2" fill="currentColor" stroke="none" />
    <path d="m3 14 4-4 3 3 2-2 3 3" strokeLinejoin="round" />
  </svg>
)

/**
 * @param {object} props
 * @param {import('@codemirror/view').EditorView|null} props.view  The editor to act on (NoteEditor's onReady).
 * @param {object} [props.capabilities]  GET /notes/capabilities. With attachments off the Image button is dimmed and does nothing.
 * @param {'desk'|'phone'|'auto'} [props.variant]  'auto' (default) is the phone bar under 600 px wide, the desk bar above.
 * @param {'preview'|'source'} [props.mode]  Shown in the desk bar's 'Live preview | Source' toggle.
 * @param {(mode: 'preview'|'source') => void} [props.onModeChange]  Passing this (or `mode`) adds the toggle to the desk bar.
 * @param {number} [props.keyboardHeight]  Override for the keyboard height (px). Default: measured from visualViewport.
 * @param {boolean} [props.alwaysVisible]  Phone bar: show it without the keyboard (demos, tests).
 * @param {object} [props.strings]  Copy overrides (see PREVIEW_STRINGS).
 * @param {string} [props.className]
 */
export function EditorToolbar({
  view,
  capabilities,
  variant = 'auto',
  mode,
  onModeChange,
  keyboardHeight: keyboardOverride,
  alwaysVisible = false,
  strings: overrides,
  className,
}) {
  const strings = mergePreviewStrings(overrides)
  const phone = useIsPhone(variant)
  const measured = useKeyboardHeight()
  const [root, setRoot] = useState(null)
  const focused = useEditorFocus(view, root)
  const keyboard = keyboardOverride ?? measured
  const fileInput = useRef(null)
  const bar = useRef(null)
  const [active, setActive] = useState(0)

  const attachments = Boolean(capabilities?.attachments)
  const accept = capabilities?.mime_allowlist?.length ? capabilities.mime_allowlist.join(',') : 'image/*'

  const run = (command) => () => {
    if (view) command(view)
  }
  const pickImage = () => {
    if (attachments) fileInput.current?.click()
  }

  const buttons = [
    { id: 'heading', label: strings.heading, text: 'H', run: run(toggleHeading) },
    { id: 'bold', label: strings.bold, text: 'B', glyph: s.glyphBold, run: run(toggleBold) },
    { id: 'italic', label: strings.italic, text: 'I', glyph: s.glyphItalic, run: run(toggleItalic) },
    { id: 'list', label: phone ? strings.list : strings.bulletedList, icon: <ListIcon />, run: run(toggleBulletList) },
    { id: 'link', label: phone ? strings.insertLink : strings.link, text: phone ? '[[' : strings.link, run: run(insertWikiLink) },
    {
      id: 'image',
      label: attachments ? (phone ? strings.addImage : strings.image) : phone ? strings.addImageOff : strings.imageOff,
      text: phone ? undefined : strings.image,
      icon: <ImageIcon />,
      off: !attachments,
      run: pickImage,
    },
  ]

  // Roving focus: one tab stop for the group, arrows move inside it.
  const onKeyDown = (event) => {
    const keys = { ArrowRight: 1, ArrowLeft: -1 }
    const nodes = [...bar.current.querySelectorAll('button')]
    const at = nodes.indexOf(document.activeElement)
    let next = null
    if (event.key in keys) next = (at + keys[event.key] + nodes.length) % nodes.length
    else if (event.key === 'Home') next = 0
    else if (event.key === 'End') next = nodes.length - 1
    if (next === null) return
    event.preventDefault()
    setActive(next)
    nodes[next].focus()
  }

  const group = (
    <div ref={bar} role="toolbar" aria-label={strings.formatting} aria-orientation="horizontal" style={s.group} onKeyDown={onKeyDown}>
      {buttons.map((button, index) => (
        <button
          key={button.id}
          type="button"
          style={button.off ? s.buttonOff : s.button}
          aria-label={button.label}
          aria-disabled={button.off ? true : undefined}
          data-action={button.id}
          tabIndex={index === active ? 0 : -1}
          onFocus={() => setActive(index)}
          // The editor keeps its caret, its selection and the keyboard.
          onMouseDown={(event) => event.preventDefault()}
          onClick={button.run}
        >
          {button.icon}
          {button.text ? <span style={button.glyph} aria-hidden="true">{button.text}</span> : null}
        </button>
      ))}
    </div>
  )

  const picker = (
    <input
      ref={fileInput}
      type="file"
      accept={accept}
      multiple
      hidden
      tabIndex={-1}
      aria-hidden="true"
      data-arpn="image-picker"
      onChange={(event) => {
        if (view) addImageFiles(view, event.target.files)
        event.target.value = ''
      }}
    />
  )

  if (phone) {
    if (!alwaysVisible && !(focused && keyboard > 0)) return picker
    return (
      <div ref={setRoot} className={className} style={s.phone(keyboard)} data-arpn="editor-toolbar" data-variant="phone">
        {group}
        <span style={s.spacer} />
        <button
          type="button"
          style={s.hide}
          data-action="hide-keyboard"
          onMouseDown={(event) => event.preventDefault()}
          onClick={() => {
            view?.contentDOM.blur()
            if (document.activeElement instanceof HTMLElement) document.activeElement.blur()
          }}
        >
          {strings.hideKeyboard}
        </button>
        {picker}
      </div>
    )
  }

  const showToggle = mode !== undefined || onModeChange !== undefined
  return (
    <div className={className} style={s.desk} data-arpn="editor-toolbar" data-variant="desk">
      {group}
      <span style={s.spacer} />
      {showToggle ? <ModeToggle view={view} mode={mode} onChange={onModeChange} strings={overrides} /> : null}
      {picker}
    </div>
  )
}
