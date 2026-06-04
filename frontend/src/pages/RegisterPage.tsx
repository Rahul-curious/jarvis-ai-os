import { FormEvent, useState } from 'react';

import { ApiError, register, UserProfile } from '../api/client';
import { RoutePath } from '../state/router';

type RegisterPageProps = {
  onAuthenticated: (user: UserProfile) => void;
  navigate: (path: RoutePath) => void;
};

export function RegisterPage({ onAuthenticated, navigate }: RegisterPageProps) {
  const [fullName, setFullName] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setIsSubmitting(true);

    try {
      const response = await register({ full_name: fullName, email, password });
      onAuthenticated(response.user);
      navigate('/dashboard');
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : 'Unable to register');
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <section className="auth-card" aria-labelledby="register-title">
      <p className="eyebrow">Open Signup</p>
      <h1 id="register-title">Create your JARVIS account</h1>
      <p className="lede">Phase 3 adds secure identity, sessions, and audit tracking.</p>

      <form onSubmit={handleSubmit}>
        <label>
          Full name
          <input
            autoComplete="name"
            name="fullName"
            onChange={(event) => setFullName(event.target.value)}
            required
            type="text"
            value={fullName}
          />
        </label>

        <label>
          Email
          <input
            autoComplete="email"
            name="email"
            onChange={(event) => setEmail(event.target.value)}
            required
            type="email"
            value={email}
          />
        </label>

        <label>
          Password
          <input
            autoComplete="new-password"
            maxLength={128}
            minLength={12}
            name="password"
            onChange={(event) => setPassword(event.target.value)}
            required
            type="password"
            value={password}
          />
        </label>

        {error ? <p className="form-error">{error}</p> : null}

        <button disabled={isSubmitting} type="submit">
          {isSubmitting ? 'Creating account...' : 'Create account'}
        </button>
      </form>

      <p className="auth-switch">
        Already registered?{' '}
        <button className="text-button" onClick={() => navigate('/login')} type="button">
          Log in
        </button>
      </p>
    </section>
  );
}
