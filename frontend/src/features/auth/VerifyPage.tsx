import { Link, useSearchParams } from 'react-router'
import { AuthCard } from './AuthCard'
import { Button } from '../../components/ui/Button'
import { useVerifyEmail } from './hooks'
import { authErrorMessage } from '../../lib/api/error-copy'

export function VerifyPage() {
  const [searchParams] = useSearchParams()
  const token = searchParams.get('token') ?? ''
  const verify = useVerifyEmail()

  return (
    <AuthCard eyebrow="One more step" title="Verify your email.">
      {verify.isSuccess ? (
        <div className="flex flex-col gap-4">
          <p className="font-body text-sm text-text-muted">{verify.data.message}</p>
          <Link to="/login">
            <Button>Go to login</Button>
          </Link>
        </div>
      ) : (
        <div className="flex flex-col gap-4">
          <p className="font-body text-sm text-text-muted">
            Click below to confirm your email address. We never verify automatically on page load,
            so this is safe even if a mail scanner opened the link first.
          </p>
          {/* Never POSTs on mount — only on explicit click, per CLAUDE.md (mail scanners execute JS). */}
          <Button onClick={() => verify.mutate(token)} disabled={!token || verify.isPending}>
            {verify.isPending ? 'Verifying…' : 'Verify my email'}
          </Button>
          {verify.isError && (
            <p role="alert" className="font-body text-sm text-status-down-text">
              {authErrorMessage(verify.error)}
            </p>
          )}
        </div>
      )}
    </AuthCard>
  )
}
