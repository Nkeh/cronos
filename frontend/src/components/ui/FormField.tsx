import type { ReactNode } from 'react'

export function FormField({
  label,
  htmlFor,
  error,
  hint,
  children,
}: {
  label: string
  htmlFor: string
  error?: string
  hint?: string
  children: ReactNode
}) {
  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor={htmlFor} className="font-body text-sm text-text-muted">
        {label}
      </label>
      {children}
      {hint && !error && <p className="font-mono text-xs text-text-muted">{hint}</p>}
      {error && (
        <p role="alert" className="font-body text-xs text-status-down-text">
          {error}
        </p>
      )}
    </div>
  )
}
