import { Navigate, Outlet } from "react-router-dom";
import { useAuth } from "../auth";

// Frontend-only gate: an authed-but-not-onboarded user is sent to /onboarding.
// The API never blocks on `onboarded` — this is purely a UX funnel.
export function RequireOnboarded() {
  const { user } = useAuth();
  if (user && !user.onboarded) return <Navigate to="/onboarding" replace />;
  return <Outlet />;
}
