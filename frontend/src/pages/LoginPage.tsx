import { FormEvent, useState } from 'react';

import { ApiError, login, UserProfile } from '../api/client';
import { RoutePath } from '../state/router';

type LoginPageProps = {
  onAuthenticated: (user: UserProfile) => void;
  navigate: (path: RoutePath) => void;
};

export function LoginPage({ onAuthenticated, navigate }: LoginPageProps) {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setIsSubmitting(true);

    try {
      const response = await login({ email, password });
      onAuthenticated(response.user);
      navigate('/dashboard');
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : 'Unable to login');
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <section className="auth-card" aria-labelledby="login-title">
      <p className="eyebrow">Secure Access</p>
      <h1 id="login-title">Log in to JARVIS</h1>
      <p className="lede">Use your Phase 3 identity account to access the control plane.</p>

      <form onSubmit={handleSubmit}>
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
            autoComplete="current-password"
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
          {isSubmitting ? 'Logging in...' : 'Log in'}
        </button>
      </form>

      <p className="auth-switch">
        Need access?{' '}
        <button className="text-button" onClick={() => navigate('/register')} type="button">
          Create an account
        </button>
      </p>
    </section>
  );
}
