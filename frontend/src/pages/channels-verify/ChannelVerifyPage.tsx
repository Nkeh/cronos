import { Link, useSearchParams } from 'react-router'
import { PageHeader } from '../../app/shell/PageHeader'
import { Button } from '../../components/ui/Button'
import { channelErrorMessage } from '../../lib/api/error-copy'
import { useVerifyChannelEmail } from '../../features/channels/hooks'

export function ChannelVerifyPage() {
  const [searchParams] = useSearchParams()
  const token = searchParams.get('token') ?? ''
  const verify = useVerifyChannelEmail()

  return (
    <div className="mx-auto max-w-md">
      <PageHeader eyebrow="One more step" title="Verify this channel." />

      {verify.isSuccess ? (
        <div className="flex flex-col gap-4">
          <p className="font-body text-sm text-text-muted">{verify.data.message}</p>
          <Link to="/settings/channels">
            <Button>Go to channels</Button>
          </Link>
        </div>
      ) : (
        <div className="flex flex-col gap-4">
          <p className="font-body text-sm text-text-muted">
            Click below to confirm this channel. We never verify automatically on page load, so
            this is safe even if a mail scanner opened the link first.
          </p>
          {/* Never POSTs on mount -- only on explicit click, per CLAUDE.md's mail-scanner rule. */}
          <Button onClick={() => verify.mutate(token)} disabled={!token || verify.isPending}>
            {verify.isPending ? 'Verifying…' : 'Verify channel'}
          </Button>
          {verify.isError && (
            <p role="alert" className="font-body text-sm text-status-down-text">
              {channelErrorMessage(verify.error)}
            </p>
          )}
        </div>
      )}
    </div>
  )
}
