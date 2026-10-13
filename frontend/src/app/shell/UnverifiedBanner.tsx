import { useResendVerification } from '../../features/auth/hooks'
import { useToast } from '../../features/toast/ToastProvider'
import { Button } from '../../components/ui/Button'
import { authErrorMessage, retryAfterMessage } from '../../lib/api/error-copy'

export function UnverifiedBanner() {
  const resend = useResendVerification()
  const { toast } = useToast()

  function handleResend() {
    resend.mutate(undefined, {
      onSuccess: (data) => toast(data.message, 'success'),
      onError: (error) => toast(retryAfterMessage(error) ?? authErrorMessage(error), 'error'),
    })
  }

  return (
    <div className="border-b border-border bg-surface-raised px-6 py-3">
      <div className="mx-auto flex max-w-5xl flex-wrap items-center justify-between gap-2">
        <p className="font-body text-sm text-text-muted">
          Verify your email to create monitors and heartbeats.
        </p>
        <Button size="sm" variant="outline" onClick={handleResend} disabled={resend.isPending}>
          {resend.isPending ? 'Sending…' : 'Resend email'}
        </Button>
      </div>
    </div>
  )
}
