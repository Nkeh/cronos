import { useState, type FormEvent } from 'react'
import { Link } from 'react-router'
import { AuthCard } from './AuthCard'
import { FormField } from '../../components/ui/FormField'
import { Input } from '../../components/ui/Input'
import { Button } from '../../components/ui/Button'
import { useRequestPasswordReset } from './hooks'

export function ForgotPage() {
  const [email, setEmail] = useState('')
  const request = useRequestPasswordReset()

  if (request.isSuccess) {
    return (
      <AuthCard eyebrow="Check your inbox" title="Reset link sent.">
        <p className="font-body text-sm text-text-muted">{request.data.message}</p>
      </AuthCard>
    )
  }

  function handleSubmit(event: FormEvent) {
    event.preventDefault()
    request.mutate(email)
  }

  return (
    <AuthCard eyebrow="Forgot your password?" title="Reset password.">
      <form onSubmit={handleSubmit} className="flex flex-col gap-4" noValidate>
        <FormField label="Email" htmlFor="email">
          <Input
            id="email"
            type="email"
            autoComplete="email"
            required
            value={email}
            onChange={(event) => setEmail(event.target.value)}
          />
        </FormField>
        <Button type="submit" disabled={request.isPending}>
          {request.isPending ? 'Sending…' : 'Send reset link'}
        </Button>
        <Link to="/login" className="font-body text-sm text-text-muted hover:text-accent">
          Back to login
        </Link>
      </form>
    </AuthCard>
  )
}
