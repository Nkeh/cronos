export function PageHeader({ eyebrow, title }: { eyebrow: string; title: string }) {
  return (
    <div className="mb-8 flex flex-col gap-2">
      <p className="font-body text-eyebrow uppercase text-text-muted">{eyebrow}</p>
      <h1 className="font-display text-display-2 text-text">{title}</h1>
    </div>
  )
}
