import * as React from "react"

const MOBILE_BREAKPOINT = 768

export function useIsMobile() {
  // FIX: Initialize state from the actual viewport on first render to avoid
  // the react-hooks/set-state-in-effect warning (React 19). The previous
  // pattern initialized to undefined then immediately set the real value
  // inside useEffect, causing an extra render cycle.
  const [isMobile, setIsMobile] = React.useState<boolean>(() => {
    if (typeof window === "undefined") return false
    return window.innerWidth < MOBILE_BREAKPOINT
  })

  React.useEffect(() => {
    const mql = window.matchMedia(`(max-width: ${MOBILE_BREAKPOINT - 1}px)`)
    const onChange = () => {
      setIsMobile(window.innerWidth < MOBILE_BREAKPOINT)
    }
    mql.addEventListener("change", onChange)
    // No setState here — initial state already correct from useState initializer.
    // Only update on subsequent viewport changes via the listener.
    return () => mql.removeEventListener("change", onChange)
  }, [])

  return isMobile
}
