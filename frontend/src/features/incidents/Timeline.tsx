import { motion, useReducedMotion } from 'motion/react'
import { CheckCircle2, Circle } from 'lucide-react'
import { GlassPanel } from '../../components/ui/GlassPanel'
import { duration, ease } from '../../components/motion/tokens'
import { causeLabel } from './causeCopy'
import type { CheckResultSummary, IncidentDetail } from '../../lib/api/types'

interface Step {
  label: string
  at: string | null
}

function stepsFor(incident: IncidentDetail): Step[] {
  return [
    { label: 'Started', at: incident.started_at },
    { label: 'Confirmed', at: incident.confirmed_at },
    { label: 'Acknowledged', at: incident.acknowledged_at },
    { label: 'Resolved', at: incident.resolved_at },
  ]
}

/** Started -> Confirmed -> Acknowledged -> Resolved, with the connecting segment filling in as
 * each milestone is reached. */
export function IncidentRail({ incident }: { incident: IncidentDetail }) {
  const steps = stepsFor(incident)
  const prefersReducedMotion = useReducedMotion()

  return (
    <GlassPanel className="p-5">
      <ol className="flex flex-col">
        {steps.map((step, index) => {
          const reached = step.at !== null
          const isLast = index === steps.length - 1
          return (
            <li key={step.label} className="relative flex gap-3 pb-6 last:pb-0">
              {!isLast && (
                <span
                  className="absolute left-[9px] top-5 h-[calc(100%-1.25rem)] w-px bg-border"
                  aria-hidden="true"
                >
                  <motion.span
                    className="block w-px bg-accent-solid"
                    initial={{ height: 0 }}
                    animate={{ height: reached ? '100%' : 0 }}
                    transition={
                      prefersReducedMotion ? { duration: 0 } : { duration: duration.base, ease }
                    }
                  />
                </span>
              )}
              <span className="relative z-10 mt-0.5 shrink-0 text-text-muted">
                {reached ? (
                  <CheckCircle2 size={18} className="text-accent-fg" />
                ) : (
                  <Circle size={18} />
                )}
              </span>
              <div className="flex flex-col">
                <span
                  className={
                    reached ? 'font-body text-sm text-text' : 'font-body text-sm text-text-muted'
                  }
                >
                  {step.label}
                </span>
                <span className="font-mono text-xs text-text-muted">
                  {step.at ? new Date(step.at).toLocaleString() : '—'}
                </span>
              </div>
            </li>
          )
        })}
      </ol>
    </GlassPanel>
  )
}

export function CheckResultList({ timeline }: { timeline: CheckResultSummary[] }) {
  if (timeline.length === 0) {
    return <p className="font-body text-sm text-text-muted">No check results recorded yet.</p>
  }
  return (
    <ul className="flex flex-col gap-1.5">
      {timeline.map((result, index) => (
        <li
          key={`${result.checked_at}-${index}`}
          className="flex flex-wrap items-center justify-between gap-3 rounded-sm border border-border px-3 py-2 font-body text-xs"
        >
          <span className={result.is_up ? 'text-status-up-text' : 'text-status-down-text'}>
            {result.is_up ? 'Up' : causeLabel(result.error_kind ?? 'down')}
          </span>
          <span className="font-mono text-text-muted">
            {result.status_code ?? '—'} · {result.response_time_ms ?? '—'}ms
            {result.suppressed ? ' · suppressed' : ''}
          </span>
          <span className="font-mono text-text-muted">
            {new Date(result.checked_at).toLocaleTimeString()}
          </span>
        </li>
      ))}
    </ul>
  )
}
