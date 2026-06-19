import { Navigate, Outlet } from "react-router-dom";
import { useAuth } from "../auth";

// No token → bounce to login. While a persisted token is still hydrating its user,
// hold render so children never see a half-initialized auth state.
export function RequireAuth() {
  const { token, loading } = useAuth();
  if (!token) return <Navigate to="/login" replace />;
  if (loading) return <div className="centered muted">Loading…</div>;
  return <Outlet />;
}
