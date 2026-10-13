import { PageHeader } from './PageHeader'

export function PlaceholderPage({
  eyebrow,
  title,
  day,
}: {
  eyebrow: string
  title: string
  day: number
}) {
  return (
    <div>
      <PageHeader eyebrow={eyebrow} title={title} />
      <p className="font-body text-sm text-text-muted">Arrives on day {day}.</p>
    </div>
  )
}
