import { useCallback, useState } from 'react';

import { UserProfile } from './api/client';
import { DashboardPage } from './pages/DashboardPage';
import { LoginPage } from './pages/LoginPage';
import { MemoryPage } from './pages/MemoryPage';
import { RegisterPage } from './pages/RegisterPage';
import { useRoute } from './state/router';

export default function App() {
  const { path, navigate } = useRoute();
  const [currentUser, setCurrentUser] = useState<UserProfile | null>(null);

  const handleAuthenticated = useCallback((user: UserProfile) => {
    setCurrentUser(user);
  }, []);

  const handleLogout = useCallback(() => {
    setCurrentUser(null);
  }, []);

  return (
    <main className="app-shell">
      {path === '/login' ? (
        <LoginPage navigate={navigate} onAuthenticated={handleAuthenticated} />
      ) : null}

      {path === '/register' ? (
        <RegisterPage navigate={navigate} onAuthenticated={handleAuthenticated} />
      ) : null}

      {path === '/dashboard' ? (
        <DashboardPage
          currentUser={currentUser}
          navigate={navigate}
          onLogout={handleLogout}
          onUserLoaded={handleAuthenticated}
        />
      ) : null}

      {path === '/memory' ? (
        <MemoryPage
          currentUser={currentUser}
          navigate={navigate}
          onLogout={handleLogout}
          onUserLoaded={handleAuthenticated}
        />
      ) : null}
    </main>
  );
}
