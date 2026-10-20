// Layout hooks. The components decide phone vs desktop from their own width (not the viewport), so
// they stay correct when a host embeds them in a narrow column. Server rendering and jsdom have no
// ResizeObserver: they get the desktop layout unless the host passes `layout`.
import { useLayoutEffect, useRef, useState } from 'react'

export const PHONE_MAX_WIDTH = 600

/**
 * @param {'auto'|'desktop'|'phone'} layout
 * @returns {[React.RefObject<HTMLElement>, boolean]} a ref for the root element and whether it is phone-sized.
 */
export function useIsPhone(layout = 'auto') {
  const ref = useRef(null)
  const [measured, setMeasured] = useState(false)
  useLayoutEffect(() => {
    if (layout !== 'auto') return undefined
    const el = ref.current
    if (!el) return undefined
    const measure = () => {
      const width = el.getBoundingClientRect().width
      if (width > 0) setMeasured(width < PHONE_MAX_WIDTH)
    }
    measure()
    if (typeof ResizeObserver === 'undefined') return undefined
    const observer = new ResizeObserver(measure)
    observer.observe(el)
    return () => observer.disconnect()
  }, [layout])
  return [ref, layout === 'phone' ? true : layout === 'desktop' ? false : measured]
}
