import { motion } from 'motion/react'
import { spring } from '../../../components/motion/tokens'

/** Shared-layout pill — Motion animates it sliding between whichever NavItem renders it active. */
export function ActivePill() {
  return (
    <motion.div
      layoutId="nav-active-pill"
      className="absolute inset-0 -z-10 rounded-full bg-accent-solid"
      transition={spring}
    />
  )
}
