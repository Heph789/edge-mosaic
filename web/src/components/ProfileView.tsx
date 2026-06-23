// Shared read-only rendering of a public profile, used by the standalone /p/{username}
// page. Kept here (not in Directory) so it has no dependency back on the Directory page.
import type { ProfileSource, PublicProfile } from "../api";
import { UnverifiedBadge } from "./UnverifiedBadge";

export function Avatar({ url, name }: { url: string | null; name: string | null }) {
  if (url) return <img className="avatar" src={url} alt="" />;
  const initial = (name ?? "?").trim().charAt(0).toUpperCase() || "?";
  return (
    <span className="avatar avatar-fallback" aria-hidden>
      {initial}
    </span>
  );
}

export function ProfileView({
  profile: p,
  pending,
  onToggleFollow,
}: {
  profile: PublicProfile;
  pending: boolean;
  onToggleFollow: (subscribe: boolean) => void;
}) {
  return (
    <>
      {p.tile_image_url && (
        <img className="profile-tile" src={p.tile_image_url} alt="" />
      )}
      <div className="profile-head">
        <Avatar url={p.profile_image_url} name={p.display_name} />
        <div className="row-text">
          <h2>{p.display_name ?? "Unnamed"}</h2>
          <span className="muted small">@{p.username}</span>
          {p.cities.length > 0 && (
            <span className="muted small">{p.cities.join(" · ")}</span>
          )}
        </div>
      </div>

      {p.bio && <p>{p.bio}</p>}

      <SourceLinks sources={p.sources} />

      {p.links.length > 0 && (
        <div className="profile-section">
          <span className="field-label">Links</span>
          <ul className="profile-links">
            {p.links.map((l, i) => (
              <li key={i}>
                <a href={l.url} target="_blank" rel="noreferrer noopener">
                  {l.label}
                </a>
              </li>
            ))}
          </ul>
        </div>
      )}

      {(p.contact_email || p.contact_telegram) && (
        <p className="muted small">
          Contact:{" "}
          {p.contact_email && (
            <a href={`mailto:${p.contact_email}`}>{p.contact_email}</a>
          )}
          {p.contact_email && p.contact_telegram && " · "}
          {p.contact_telegram && (
            <a
              href={`https://t.me/${p.contact_telegram}`}
              target="_blank"
              rel="noreferrer noopener"
            >
              @{p.contact_telegram}
            </a>
          )}
        </p>
      )}

      <button
        className={p.is_subscribed ? "btn btn-subscribed" : "btn btn-primary"}
        onClick={() => onToggleFollow(!p.is_subscribed)}
        disabled={pending}
      >
        {p.is_subscribed ? "Following" : "Follow"}
      </button>
    </>
  );
}

// The feeder's content feeds, as clickable links (labelled by pulled title, with a
// platform pill). Falls back to a muted note when the feeder has no sources.
function SourceLinks({ sources }: { sources: ProfileSource[] }) {
  if (sources.length === 0)
    return <span className="muted small">no sources yet</span>;
  return (
    <div className="profile-section">
      <span className="field-label">Feeds</span>
      <ul className="profile-links profile-sources">
        {sources.map((s, i) => (
          <li key={i}>
            <a href={s.url} target="_blank" rel="noreferrer noopener">
              {s.title ?? s.url}
            </a>
            <span className="pill">{s.label}</span>
            {s.status === "unverified" && <UnverifiedBadge />}
          </li>
        ))}
      </ul>
    </div>
  );
}
