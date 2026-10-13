import { PageHeader } from '../../app/shell/PageHeader'

export function OverviewPage() {
  return (
    <div>
      <PageHeader eyebrow="Live checks" title="Overview." />
      <p className="font-body text-sm text-text-muted">
        Monitor counts by status land with the monitor UI (Day 5b).
      </p>
    </div>
  )
}
