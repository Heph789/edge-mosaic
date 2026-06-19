// Auth context: bearer token in localStorage + the current User, hydrated from GET /me
// on a cold load. The global 401 handler lives in api.ts; this just owns app-side state.
import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { api, TOKEN_KEY, type User } from "./api";

type AuthContextValue = {
  token: string | null;
  user: User | null;
  /** True while we're hydrating the user from a persisted token on cold load. */
  loading: boolean;
  login: (token: string, user: User) => void;
  logout: () => Promise<void>;
  refreshUser: () => Promise<User>;
  /** Replace the cached user (e.g. after a PATCH /me returns the fresh row). */
  applyUser: (user: User) => void;
};

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [token, setToken] = useState<string | null>(() => localStorage.getItem(TOKEN_KEY));
  const [user, setUser] = useState<User | null>(null);
  // Only "loading" if we have a token to resolve; a logged-out cold load is settled.
  const [loading, setLoading] = useState<boolean>(() => localStorage.getItem(TOKEN_KEY) != null);

  function clearLocal() {
    localStorage.removeItem(TOKEN_KEY);
    setToken(null);
    setUser(null);
  }

  function login(newToken: string, newUser: User) {
    localStorage.setItem(TOKEN_KEY, newToken);
    setToken(newToken);
    setUser(newUser);
    setLoading(false);
  }

  async function logout() {
    try {
      await api.logout(); // revoke the session row server-side (best-effort)
    } catch {
      /* already gone / network — clear locally regardless */
    }
    clearLocal();
  }

  async function refreshUser() {
    const fresh = await api.getMe();
    setUser(fresh);
    return fresh;
  }

  // Cold load with a persisted token but no user yet → hydrate via GET /me.
  // A failure here means the token is stale (a 401 already redirected via api.ts),
  // so just settle into a logged-out state.
  useEffect(() => {
    if (!token || user) {
      setLoading(false);
      return;
    }
    let cancelled = false;
    api
      .getMe()
      .then((u) => {
        if (!cancelled) setUser(u);
      })
      .catch(() => {
        if (!cancelled) clearLocal();
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token]);

  return (
    <AuthContext.Provider
      value={{ token, user, loading, login, logout, refreshUser, applyUser: setUser }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within <AuthProvider>");
  return ctx;
}
