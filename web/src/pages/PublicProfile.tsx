import { Link, useParams } from "react-router-dom";
import { ProfileView } from "../components/ProfileView";
import { useProfile, useToggleFollowProfile } from "../hooks/queries";

// Standalone, shareable profile at /p/{username}. Login-gated like the rest of the app
// (it lives under RequireAuth + RequireOnboarded), and a hidden/unknown profile 404s.
export function PublicProfile() {
  const { username = "" } = useParams();
  const { data: p, isError } = useProfile(username);
  const follow = useToggleFollowProfile(username);

  return (
    <div className="page stack">
      <Link to="/directory" className="btn btn-ghost">
        ← Directory
      </Link>
      <div className="card stack">
        {isError ? (
          <p className="error">This profile doesn't exist or isn't visible to you.</p>
        ) : !p ? (
          <p className="muted">Loading…</p>
        ) : (
          <ProfileView
            profile={p}
            pending={follow.isPending}
            onToggleFollow={(subscribe) =>
              follow.mutate({ feederId: p.id, subscribe })
            }
          />
        )}
      </div>
    </div>
  );
}
