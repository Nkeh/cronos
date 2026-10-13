import { Activity, AlertTriangle, Globe, HeartPulse, Home, type LucideIcon } from 'lucide-react'

export interface NavItemConfig {
  to: string
  label: string
  icon: LucideIcon
}

export const navItems: NavItemConfig[] = [
  { to: '/', label: 'Overview', icon: Home },
  { to: '/monitors', label: 'Monitors', icon: Activity },
  { to: '/heartbeats', label: 'Heartbeats', icon: HeartPulse },
  { to: '/incidents', label: 'Incidents', icon: AlertTriangle },
  { to: '/status-pages', label: 'Status pages', icon: Globe },
]
