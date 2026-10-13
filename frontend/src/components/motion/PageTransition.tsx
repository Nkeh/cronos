import { AnimatePresence, motion } from 'motion/react'
import { useLocation, Outlet } from 'react-router'
import { duration, ease } from './tokens'

/** Fade + 8px rise on route change. No blur — CLAUDE.md overrides the SRS's blur mention. */
export function PageTransition() {
  const location = useLocation()
  return (
    <AnimatePresence mode="wait" initial={false}>
      <motion.div
        key={location.pathname}
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        exit={{ opacity: 0, y: -8 }}
        transition={{ duration: duration.base, ease }}
      >
        <Outlet />
      </motion.div>
    </AnimatePresence>
  )
}
