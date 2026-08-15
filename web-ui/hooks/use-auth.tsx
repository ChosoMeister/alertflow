'use client';

import { useEffect, useState, useCallback } from 'react';
import { useRouter } from '@/navigation';
import { api } from '@/lib/api';

/**
 * Self-contained auth hook — no Provider needed.
 * Reads token from localStorage, redirects to login if missing.
 * Drop-in replacement for the manual localStorage check pattern.
 */
export function useAuth() {
  const router = useRouter();
  const [token, setToken] = useState<string | null>(null);
  const [user, setUser] = useState<{ username: string; role: string } | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    const storedToken = localStorage.getItem('alertflow_token');
    const storedUser = localStorage.getItem('alertflow_user');

    if (!storedToken) {
      router.push('/login');
      setIsLoading(false);
      return;
    }

    setToken(storedToken);

    if (storedUser) {
      try {
        setUser(JSON.parse(storedUser));
      } catch {
        localStorage.removeItem('alertflow_user');
      }
    }

    setIsLoading(false);
  }, [router]);

  const logout = useCallback(async () => {
    await api.logout().catch(() => undefined);
    localStorage.removeItem('alertflow_token');
    localStorage.removeItem('alertflow_user');
    setToken(null);
    setUser(null);
    router.push('/login');
  }, [router]);

  return { token, user, isLoading, logout };
}
