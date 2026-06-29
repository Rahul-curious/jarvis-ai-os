import { useCallback, useEffect, useState } from 'react';

export type RoutePath = '/login' | '/register' | '/dashboard' | '/memory' | '/knowledge' | '/knowledge/upload';

const knownRoutes = new Set<RoutePath>([
  '/login',
  '/register',
  '/dashboard',
  '/memory',
  '/knowledge',
  '/knowledge/upload',
]);

export function useRoute() {
  const [path, setPath] = useState<RoutePath>(getCurrentRoute());

  useEffect(() => {
    const onPopState = () => setPath(getCurrentRoute());
    window.addEventListener('popstate', onPopState);
    return () => window.removeEventListener('popstate', onPopState);
  }, []);

  const navigate = useCallback((nextPath: RoutePath) => {
    window.history.pushState({}, '', nextPath);
    setPath(nextPath);
  }, []);

  return { path, navigate };
}

function getCurrentRoute(): RoutePath {
  const path = window.location.pathname as RoutePath;
  if (knownRoutes.has(path)) {
    return path;
  }
  return '/login';
}
