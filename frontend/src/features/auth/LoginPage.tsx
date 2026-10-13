import { useState, type FormEvent } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router'
import { AuthCard } from './AuthCard'
import { FormField } from '../../components/ui/FormField'
import { Input } from '../../components/ui/Input'
import { Button } from '../../components/ui/Button'
import { useLogin } from './hooks'
import { authErrorMessage, retryAfterMessage } from '../../lib/api/error-copy'

export function LoginPage() {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [searchParams] = useSearchParams()
  const navigate = useNavigate()
  const login = useLogin()

  function handleSubmit(event: FormEvent) {
    event.preventDefault()
    login.mutate(
      { email, password },
      {
        onSuccess: () => {
          const next = searchParams.get('next')
          navigate(next && next.startsWith('/') ? next : '/', { replace: true })
        },
      },
    )
  }

  const errorMessage = login.isError
    ? (retryAfterMessage(login.error) ?? authErrorMessage(login.error))
    : null

  return (
    <AuthCard eyebrow="Welcome back" title="Log in.">
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
        <FormField label="Password" htmlFor="password">
          <Input
            id="password"
            type="password"
            autoComplete="current-password"
            required
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            invalid={login.isError}
          />
        </FormField>
        {errorMessage && (
          <p role="alert" className="font-body text-sm text-status-down-text">
            {errorMessage}
          </p>
        )}
        <Button type="submit" disabled={login.isPending}>
          {login.isPending ? 'Logging in…' : 'Log in'}
        </Button>
        <div className="flex justify-between font-body text-sm text-text-muted">
          <Link to="/forgot" className="hover:text-accent">
            Forgot password?
          </Link>
          <Link to="/signup" className="hover:text-accent">
            Create account
          </Link>
        </div>
      </form>
    </AuthCard>
  )
}
