import { Navigate, Route, Routes } from "react-router-dom";
import { AppShell } from "./components/AppShell";
import { RequireAuth } from "./components/RequireAuth";
import { RequireOnboarded } from "./components/RequireOnboarded";
import { Login } from "./pages/Login";
import { Verify } from "./pages/Verify";
import { Unsubscribe } from "./pages/Unsubscribe";
import { Onboarding } from "./pages/Onboarding";
import { Directory } from "./pages/Directory";
import { Digest } from "./pages/Digest";
import { Profile } from "./pages/Profile";
import { PublicProfile } from "./pages/PublicProfile";

export function AppRoutes() {
  return (
    <Routes>
      {/* public */}
      <Route path="/login" element={<Login />} />
      <Route path="/auth/verify" element={<Verify />} />
      <Route path="/unsubscribe" element={<Unsubscribe />} />

      {/* authed, outside the tab shell */}
      <Route element={<RequireAuth />}>
        <Route path="/onboarding" element={<Onboarding />} />

        {/* authed + onboarded, inside the 3-tab shell */}
        <Route element={<RequireOnboarded />}>
          <Route path="/" element={<AppShell />}>
            <Route index element={<Navigate to="/directory" replace />} />
            <Route path="directory" element={<Directory />} />
            <Route path="digest" element={<Digest />} />
            <Route path="profile" element={<Profile />} />
            <Route path="p/:username" element={<PublicProfile />} />
          </Route>
        </Route>
      </Route>

      {/* unknown → funnel through the guards (→ /directory when authed, else /login) */}
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
