import type { ReactNode } from 'react'

export function AuthCard({
  eyebrow,
  title,
  children,
}: {
  eyebrow: string
  title: string
  children: ReactNode
}) {
  return (
    <div className="mx-auto flex min-h-screen max-w-md flex-col justify-center px-6 py-16">
      <div className="ambient-bg" />
      <p className="font-body text-eyebrow uppercase text-text-muted">{eyebrow}</p>
      <h1 className="mb-8 font-display text-display-2 text-text">{title}</h1>
      {children}
    </div>
  )
}
