export function IncidentsBadge({ count }: { count: number }) {
  if (count <= 0) return null
  return (
    <span
      className="absolute -right-1.5 -top-1.5 flex h-4 min-w-4 animate-pulse items-center justify-center rounded-full bg-status-down-dot px-1 font-mono text-[10px] text-white motion-reduce:animate-none"
      aria-hidden="true"
    >
      {count}
    </span>
  )
}
