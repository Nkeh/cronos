import { useEffect, useRef } from 'react'
import { animate, useMotionValue, useMotionValueEvent, useReducedMotion } from 'motion/react'
import { duration as durationTokens } from './tokens'

/** Count-up for numeric stats. Unused until later days wire real numeric data. */
export function NumberTicker({ value, className }: { value: number; className?: string }) {
  const spanRef = useRef<HTMLSpanElement>(null)
  const motionValue = useMotionValue(0)
  const prefersReducedMotion = useReducedMotion()

  useMotionValueEvent(motionValue, 'change', (latest) => {
    if (spanRef.current) spanRef.current.textContent = Math.round(latest).toString()
  })

  useEffect(() => {
    if (prefersReducedMotion) {
      motionValue.set(value)
      return
    }
    const controls = animate(motionValue, value, { duration: durationTokens.slow })
    return () => controls.stop()
  }, [value, prefersReducedMotion, motionValue])

  return (
    <span ref={spanRef} className={className} data-numeric>
      0
    </span>
  )
}
