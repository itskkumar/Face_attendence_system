"use client";
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { api, ApiError, setCsrf } from "./api";
import type { AuthState, User } from "./types";

interface AuthCtx {
  user: User | null;
  loading: boolean;
  mustReset: boolean;
  refresh: () => Promise<void>;
  login: (username: string, password: string) => Promise<AuthState>;
  logout: () => Promise<void>;
  applyAuth: (s: { user: User; csrf_token: string; must_reset_password?: boolean }) => void;
}

const Ctx = createContext<AuthCtx | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [mustReset, setMustReset] = useState(false);
  const [loading, setLoading] = useState(true);

  const applyAuth = useCallback((s: { user: User; csrf_token: string; must_reset_password?: boolean }) => {
    setCsrf(s.csrf_token);
    setUser(s.user);
    setMustReset(Boolean(s.must_reset_password));
  }, []);

  const refresh = useCallback(async () => {
    try {
      applyAuth(await api<AuthState>("/auth/me"));
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) { setCsrf(null); setUser(null); }
    } finally {
      setLoading(false);
    }
  }, [applyAuth]);

  useEffect(() => { void refresh(); }, [refresh]);

  const login = useCallback(async (username: string, password: string) => {
    const s = await api<AuthState>("/auth/login", { method: "POST", body: { username, password } });
    applyAuth(s);
    return s;
  }, [applyAuth]);

  const logout = useCallback(async () => {
    try { await api("/auth/logout", { method: "POST" }); } finally { setCsrf(null); setUser(null); }
  }, []);

  const value = useMemo(() => ({ user, loading, mustReset, refresh, login, logout, applyAuth }), [user, loading, mustReset, refresh, login, logout, applyAuth]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useAuth(): AuthCtx {
  const c = useContext(Ctx);
  if (!c) throw new Error("useAuth must be used inside <AuthProvider>");
  return c;
}
