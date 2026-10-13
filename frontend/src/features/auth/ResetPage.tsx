import { useState, type FormEvent } from 'react'
import { useNavigate, useSearchParams } from 'react-router'
import { AuthCard } from './AuthCard'
import { FormField } from '../../components/ui/FormField'
import { Input } from '../../components/ui/Input'
import { Button } from '../../components/ui/Button'
import { useResetPassword } from './hooks'
import { authErrorMessage } from '../../lib/api/error-copy'

export function ResetPage() {
  const [searchParams] = useSearchParams()
  const navigate = useNavigate()
  const token = searchParams.get('token') ?? ''
  const [password, setPassword] = useState('')
  const reset = useResetPassword()

  function handleSubmit(event: FormEvent) {
    event.preventDefault()
    reset.mutate(
      { token, password },
      { onSuccess: () => navigate('/login', { replace: true }) },
    )
  }

  return (
    <AuthCard eyebrow="Choose a new password" title="Reset password.">
      <form onSubmit={handleSubmit} className="flex flex-col gap-4" noValidate>
        <FormField label="New password" htmlFor="password" hint="At least 8 characters.">
          <Input
            id="password"
            type="password"
            autoComplete="new-password"
            required
            minLength={8}
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            invalid={reset.isError}
          />
        </FormField>
        {reset.isError && (
          <p role="alert" className="font-body text-sm text-status-down-text">
            {authErrorMessage(reset.error)}
          </p>
        )}
        <Button type="submit" disabled={!token || reset.isPending}>
          {reset.isPending ? 'Resetting…' : 'Reset password'}
        </Button>
      </form>
    </AuthCard>
  )
}
