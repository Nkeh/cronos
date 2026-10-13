import { useEffect, useRef, useState } from 'react'

/** Compacts the navbar's padding on scroll-down, restores on scroll-up. Never hides it. */
export function useScrollDirection() {
  const [isCompact, setIsCompact] = useState(false)
  const lastY = useRef(0)

  useEffect(() => {
    function onScroll() {
      const y = window.scrollY
      if (y > lastY.current && y > 80) setIsCompact(true)
      else if (y < lastY.current) setIsCompact(false)
      lastY.current = y
    }
    window.addEventListener('scroll', onScroll, { passive: true })
    return () => window.removeEventListener('scroll', onScroll)
  }, [])

  return isCompact
}
