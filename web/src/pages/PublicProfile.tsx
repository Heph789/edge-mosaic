import { Link, useParams } from "react-router-dom";
import { ChevronLeft } from "lucide-react";
import { ProfileView } from "../components/ProfileView";
import { useProfile, useToggleFollowProfile } from "../hooks/queries";

// Standalone, shareable profile at /p/{username}. Login-gated like the rest of the app
// (it lives under RequireAuth + RequireOnboarded), and a hidden/unknown profile 404s. This
// is the full-page fallback; opened from within the Directory it renders as a Sheet instead.
export function PublicProfile() {
  const { username = "" } = useParams();
  const { data: p, isError } = useProfile(username);
  const follow = useToggleFollowProfile(username);

  return (
    <div className="absolute inset-0 overflow-y-auto">
      <div className="mx-auto flex w-full max-w-2xl flex-col gap-4 px-4 py-5">
        <Link
          to="/directory"
          className="inline-flex items-center gap-1 self-start text-sm text-muted-foreground hover:text-foreground"
        >
          <ChevronLeft className="size-4" />
          Directory
        </Link>
        <div className="rounded-xl border border-border bg-card p-5">
          {isError ? (
            <p className="text-sm text-destructive">
              This profile doesn't exist or isn't visible to you.
            </p>
          ) : !p ? (
            <p className="text-muted-foreground">Loading…</p>
          ) : (
            <ProfileView
              profile={p}
              pending={follow.isPending}
              onToggleFollow={(subscribe) => follow.mutate({ feederId: p.id, subscribe })}
            />
          )}
        </div>
      </div>
    </div>
  );
}
