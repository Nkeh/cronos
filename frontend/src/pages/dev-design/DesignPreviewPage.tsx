import { Activity, AlertTriangle, Globe, HeartPulse, Home, Search, User } from 'lucide-react'
import { useTheme } from '../../features/theme/ThemeProvider'
import { Button } from '../../components/ui/Button'
import { Input } from '../../components/ui/Input'
import { GlassPanel } from '../../components/ui/GlassPanel'
import { StatusPill, type Status } from '../../components/ui/StatusPill'
import { Skeleton } from '../../components/ui/Skeleton'
import { durationMs } from '../../components/motion/tokens'

const swatches: { name: string; varName: string }[] = [
  { name: 'bg', varName: '--bg' },
  { name: 'surface', varName: '--surface' },
  { name: 'surface-raised', varName: '--surface-raised' },
  { name: 'border', varName: '--border' },
  { name: 'text', varName: '--text' },
  { name: 'text-muted', varName: '--text-muted' },
  { name: 'accent', varName: '--accent' },
  { name: 'accent-solid', varName: '--accent-solid' },
]

const statuses: { status: Status; label: string }[] = [
  { status: 'up', label: 'Up' },
  { status: 'down', label: '2 Down' },
  { status: 'degraded', label: 'Degraded' },
  { status: 'paused', label: 'Paused' },
]

const navItems = [
  { icon: Home, label: 'Overview' },
  { icon: Activity, label: 'Monitors' },
  { icon: HeartPulse, label: 'Heartbeats' },
  { icon: AlertTriangle, label: 'Incidents' },
  { icon: Globe, label: 'Status pages' },
]

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="flex flex-col gap-4">
      <h2 className="font-display text-heading-3 text-text">{title}</h2>
      {children}
    </section>
  )
}

export function DesignPreviewPage() {
  const { theme, resolvedTheme, setTheme } = useTheme()

  return (
    <main className="mx-auto flex max-w-4xl flex-col gap-12 px-6 py-16">
      <div className="ambient-bg" />

      <header className="flex flex-col gap-4">
        <p className="font-body text-eyebrow uppercase text-text-muted">Day 5 — Checkpoint A</p>
        <h1 className="font-display text-display-1 text-text">Design system.</h1>
        <div className="flex items-center gap-2">
          {(['system', 'light', 'dark'] as const).map((mode) => (
            <Button
              key={mode}
              size="sm"
              variant={theme === mode ? 'solid' : 'outline'}
              onClick={() => setTheme(mode)}
            >
              {mode}
            </Button>
          ))}
          <span className="font-mono text-sm text-text-muted">resolved: {resolvedTheme}</span>
        </div>
      </header>

      <Section title="Palette">
        <div className="grid grid-cols-4 gap-4">
          {swatches.map((s) => (
            <div key={s.name} className="flex flex-col gap-2">
              <div
                className="h-16 rounded-sm border border-border"
                style={{ backgroundColor: `var(${s.varName})` }}
              />
              <span className="font-mono text-xs text-text-muted">{s.name}</span>
            </div>
          ))}
        </div>
      </Section>

      <Section title="Type scale">
        <div className="flex flex-col gap-3">
          <p className="font-display text-display-1 text-text">Monitors.</p>
          <p className="font-display text-display-2 text-text">Incidents.</p>
          <p className="font-display text-heading-3 text-text">Heartbeats.</p>
          <p className="font-body text-eyebrow uppercase text-text-muted">Live checks</p>
          <p className="font-body text-body text-text">
            The quick brown fox jumps over the lazy dog — Outfit body copy.
          </p>
          <p className="font-mono text-mono text-text" data-numeric>
            204ms · 99.98% · 2026-10-13T00:00:00Z
          </p>
        </div>
      </Section>

      <Section title="Status set">
        <div className="flex gap-3">
          {statuses.map((s) => (
            <StatusPill key={s.status} status={s.status} label={s.label} />
          ))}
        </div>
      </Section>

      <Section title="Buttons">
        <div className="flex items-center gap-3">
          <Button variant="solid">Create monitor</Button>
          <Button variant="outline">Cancel</Button>
          <Button variant="ghost">Dismiss</Button>
          <Button variant="solid" disabled>
            Disabled
          </Button>
        </div>
      </Section>

      <Section title="Inputs">
        <div className="flex max-w-sm flex-col gap-3">
          <Input placeholder="https://example.com" />
          <Input placeholder="Invalid URL" invalid defaultValue="not-a-url" />
        </div>
      </Section>

      <Section title="Glass panel">
        <GlassPanel className="p-6 shadow-glow">
          <p className="font-body text-sm text-text">
            Glass surface — 16px backdrop blur, hairline border, medium glow.
          </p>
        </GlassPanel>
      </Section>

      <Section title="Skeleton">
        <Skeleton className="h-6 w-48" />
      </Section>

      <Section title="Navbar capsule (static preview)">
        <div className="flex justify-center py-8">
          <div className="flex items-center gap-1 rounded-full border border-glass-border bg-glass-bg px-2 py-2 backdrop-blur-glass">
            {navItems.map(({ icon: Icon, label }, i) => (
              <div
                key={label}
                className={
                  'flex items-center gap-2 rounded-full px-3 py-2 font-body text-sm ' +
                  (i === 0 ? 'bg-accent-solid text-accent-fg' : 'text-text-muted')
                }
              >
                <Icon size={16} />
                <span className="hidden sm:inline">{label}</span>
              </div>
            ))}
            <div className="mx-1 h-5 w-px bg-border" />
            <div className="flex items-center gap-2 rounded-full px-3 py-2 text-text-muted">
              <Search size={16} />
            </div>
            <div className="flex items-center gap-2 rounded-full px-3 py-2 text-text-muted">
              <User size={16} />
            </div>
          </div>
        </div>
      </Section>

      <Section title="Motion tokens">
        <div className="flex flex-col gap-2 font-mono text-sm text-text-muted">
          <p>fast: {durationMs.fast}ms · base: {durationMs.base}ms · slow: {durationMs.slow}ms</p>
          <p>ease: cubic-bezier(0.4, 0, 0.2, 1) · spring: stiffness 300 / damping 30</p>
        </div>
        <div
          className="h-12 w-12 cursor-pointer rounded-sm bg-accent-solid transition-transform duration-(--duration-base) ease-(--ease) hover:translate-x-8"
          title="Hover to see the base-duration transform transition"
        />
      </Section>
    </main>
  )
}
