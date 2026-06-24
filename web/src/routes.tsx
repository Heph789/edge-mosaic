import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import type { Location } from "react-router-dom";
import { AppShell } from "./components/AppShell";
import { RequireAuth } from "./components/RequireAuth";
import { RequireOnboarded } from "./components/RequireOnboarded";
import { ProfileSheet } from "./components/ProfileSheet";
import { Login } from "./pages/Login";
import { Verify } from "./pages/Verify";
import { Unsubscribe } from "./pages/Unsubscribe";
import { Onboarding } from "./pages/Onboarding";
import { Directory } from "./pages/Directory";
import { Digest } from "./pages/Digest";
import { Profile } from "./pages/Profile";
import { PublicProfile } from "./pages/PublicProfile";

export function AppRoutes() {
  const location = useLocation();
  // When a profile is opened from inside the Directory we stash the originating location in
  // navigation state. The main <Routes> renders that background (so the Directory stays put)
  // while a second <Routes> layers the profile Sheet on top. A direct hit / refresh on
  // /p/:username has no background → it renders the full standalone page instead.
  const background = (location.state as { backgroundLocation?: Location } | null)
    ?.backgroundLocation;

  return (
    <>
      <Routes location={background ?? location}>
        {/* public */}
        <Route path="/login" element={<Login />} />
        <Route path="/auth/verify" element={<Verify />} />
        <Route path="/unsubscribe" element={<Unsubscribe />} />

        {/* authed, outside the tab shell */}
        <Route element={<RequireAuth />}>
          <Route path="/onboarding" element={<Onboarding />} />

          {/* authed + onboarded, inside the tab shell */}
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

      {/* Profile overlay, only when opened over a background. */}
      {background && (
        <Routes>
          <Route path="/p/:username" element={<ProfileSheet />} />
        </Routes>
      )}
    </>
  );
}
