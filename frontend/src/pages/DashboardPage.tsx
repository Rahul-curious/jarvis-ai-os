import { useEffect, useState } from 'react';

import { getCurrentUser, logout, UserProfile } from '../api/client';
import { RoutePath } from '../state/router';

type DashboardPageProps = {
  currentUser: UserProfile | null;
  navigate: (path: RoutePath) => void;
  onLogout: () => void;
  onUserLoaded: (user: UserProfile) => void;
};

export function DashboardPage({
  currentUser,
  navigate,
  onLogout,
  onUserLoaded,
}: DashboardPageProps) {
  const [isLoading, setIsLoading] = useState(currentUser === null);

  useEffect(() => {
    let isMounted = true;

    async function loadProfile() {
      try {
        const user = await getCurrentUser();
        if (isMounted) {
          onUserLoaded(user);
        }
      } catch {
        if (isMounted) {
          navigate('/login');
        }
      } finally {
        if (isMounted) {
          setIsLoading(false);
        }
      }
    }

    if (currentUser === null) {
      void loadProfile();
    }

    return () => {
      isMounted = false;
    };
  }, [currentUser, navigate, onUserLoaded]);

  async function handleLogout() {
    await logout();
    onLogout();
    navigate('/login');
  }

  if (isLoading) {
    return <p className="status-message">Loading secure profile...</p>;
  }

  if (currentUser === null) {
    return null;
  }

  return (
    <section className="dashboard" aria-labelledby="dashboard-title">
      <div>
        <p className="eyebrow">Control Plane</p>
        <h1 id="dashboard-title">Welcome, {currentUser.full_name}</h1>
        <p className="lede">
          Authentication, PostgreSQL-backed sessions, audit logging, memory, and the
          Phase 5 RAG Knowledge Engine are active. Agents, browser automation, and voice
          remain intentionally disabled for this phase.
        </p>
      </div>

      <dl className="profile-grid">
        <div>
          <dt>Email</dt>
          <dd>{currentUser.email}</dd>
        </div>
        <div>
          <dt>Role</dt>
          <dd>{currentUser.is_admin ? 'Admin' : 'User'}</dd>
        </div>
        <div>
          <dt>Status</dt>
          <dd>{currentUser.is_active ? 'Active' : 'Inactive'}</dd>
        </div>
        <div>
          <dt>Last login</dt>
          <dd>{currentUser.last_login_at ?? 'Current session'}</dd>
        </div>
      </dl>

      <div className="dashboard-actions">
        <button onClick={() => navigate('/memory')} type="button">
          Open memory dashboard
        </button>
        <button onClick={() => navigate('/knowledge')} type="button">
          Open knowledge base
        </button>
        <button className="secondary-button" onClick={handleLogout} type="button">
          Log out
        </button>
      </div>
    </section>
  );
}
