// How tall the on-screen keyboard is, from visualViewport (the pattern PT's lib/useKeyboardHeight.js ships:
// layout viewport minus visual viewport). 0 when there is no keyboard or no visualViewport. Also counts the
// visual viewport's own scroll, so a bar pinned to the bottom of the layout viewport lands on the keyboard's
// top edge even when iOS has scrolled the page under it.
import { useEffect, useState } from 'react'

const MIN_KEYBOARD_HEIGHT = 100

export function useKeyboardHeight() {
  const [height, setHeight] = useState(0)

  useEffect(() => {
    const vv = typeof window === 'undefined' ? null : window.visualViewport
    if (!vv) return undefined
    const update = () => {
      const covered = window.innerHeight - vv.height
      setHeight(covered > MIN_KEYBOARD_HEIGHT ? Math.max(0, Math.round(covered - vv.offsetTop)) : 0)
    }
    update()
    vv.addEventListener('resize', update)
    vv.addEventListener('scroll', update)
    return () => {
      vv.removeEventListener('resize', update)
      vv.removeEventListener('scroll', update)
    }
  }, [])

  return height
}
