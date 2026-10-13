import { useState, type FormEvent } from 'react'
import { Link } from 'react-router'
import { AuthCard } from './AuthCard'
import { FormField } from '../../components/ui/FormField'
import { Input } from '../../components/ui/Input'
import { Button } from '../../components/ui/Button'
import { useSignup } from './hooks'
import { authErrorMessage } from '../../lib/api/error-copy'
import { ApiError } from '../../lib/api/errors'

export function SignupPage() {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const signup = useSignup()

  if (signup.isSuccess) {
    return (
      <AuthCard eyebrow="Almost there" title="Check your email.">
        <p className="font-body text-sm text-text-muted">{signup.data.message}</p>
      </AuthCard>
    )
  }

  function handleSubmit(event: FormEvent) {
    event.preventDefault()
    signup.mutate({ email, password })
  }

  const isPasswordError = signup.isError && signup.error instanceof ApiError && signup.error.field === 'password'
  const fieldError = isPasswordError ? authErrorMessage(signup.error) : undefined
  const formError = signup.isError && !isPasswordError ? authErrorMessage(signup.error) : null

  return (
    <AuthCard eyebrow="Get started" title="Create your account.">
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
        <FormField
          label="Password"
          htmlFor="password"
          error={fieldError}
          hint="At least 8 characters. Avoid common passwords."
        >
          <Input
            id="password"
            type="password"
            autoComplete="new-password"
            required
            minLength={8}
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            invalid={isPasswordError}
          />
        </FormField>
        {formError && (
          <p role="alert" className="font-body text-sm text-status-down-text">
            {formError}
          </p>
        )}
        <Button type="submit" disabled={signup.isPending}>
          {signup.isPending ? 'Creating account…' : 'Create account'}
        </Button>
        <p className="font-body text-sm text-text-muted">
          Already have an account?{' '}
          <Link to="/login" className="hover:text-accent">
            Log in
          </Link>
        </p>
      </form>
    </AuthCard>
  )
}
