import { useEffect, useState } from "react";
import type { Discover, ProfileSource } from "../api";
import { platformLabel } from "../components/SourcesEditor";
import { useDiscover, useProfile, useToggleSubscribe } from "../hooks/queries";

// Debounce the raw input so we don't fire a /discover request on every keystroke (~300ms).
function useDebouncedValue<T>(value: T, delayMs: number): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const id = setTimeout(() => setDebounced(value), delayMs);
    return () => clearTimeout(id);
  }, [value, delayMs]);
  return debounced;
}

export function Directory() {
  const [query, setQuery] = useState("");
  const [openId, setOpenId] = useState<number | null>(null);
  const debounced = useDebouncedValue(query, 300);
  const term = debounced.trim();
  const { data, isError } = useDiscover(term);
  const toggle = useToggleSubscribe(term);

  return (
    <div className="page stack">
      <h1>Directory</h1>
      <input
        className="search"
        type="search"
        autoFocus
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        placeholder="Filter people by name…"
      />

      {isError ? (
        <p className="error">Couldn't load the directory. Try again.</p>
      ) : data && data.length === 0 ? (
        <p className="muted">
          {term.length === 0 ? "No one to show yet." : `No one matches “${term}”.`}
        </p>
      ) : !data ? (
        <p className="muted">Loading…</p>
      ) : (
        <ul className="list">
          {data.map((row) => (
            <DiscoverRow
              key={row.user_id}
              row={row}
              pending={toggle.isPending}
              onOpen={() => setOpenId(row.user_id)}
              onToggle={() =>
                toggle.mutate({ userId: row.user_id, subscribe: !row.is_subscribed })
              }
            />
          ))}
        </ul>
      )}

      {openId != null && (
        <ProfileModal
          id={openId}
          onClose={() => setOpenId(null)}
          onToggle={(subscribe) => toggle.mutate({ userId: openId, subscribe })}
        />
      )}
    </div>
  );
}

export function Avatar({ url, name }: { url: string | null; name: string | null }) {
  if (url) return <img className="avatar" src={url} alt="" />;
  const initial = (name ?? "?").trim().charAt(0).toUpperCase() || "?";
  return (
    <span className="avatar avatar-fallback" aria-hidden>
      {initial}
    </span>
  );
}

function DiscoverRow({
  row,
  pending,
  onOpen,
  onToggle,
}: {
  row: Discover;
  pending: boolean;
  onOpen: () => void;
  onToggle: () => void;
}) {
  return (
    <li className="row">
      <button className="row-main row-open" onClick={onOpen} type="button">
        <Avatar url={row.profile_image_url} name={row.display_name} />
        <span className="row-text">
          <span className="row-name">{row.display_name ?? "Unnamed"}</span>
          <Platforms platforms={row.platforms} />
        </span>
      </button>
      <button
        className={row.is_subscribed ? "btn btn-subscribed" : "btn btn-primary"}
        onClick={onToggle}
        disabled={pending}
      >
        {row.is_subscribed ? "Following" : "Follow"}
      </button>
    </li>
  );
}

function ProfileModal({
  id,
  onClose,
  onToggle,
}: {
  id: number;
  onClose: () => void;
  onToggle: (subscribe: boolean) => void;
}) {
  const { data: p, isError } = useProfile(id);

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal card stack" onClick={(e) => e.stopPropagation()}>
        <button className="modal-close btn btn-ghost" onClick={onClose} aria-label="Close">
          ✕
        </button>
        {isError ? (
          <p className="error">Couldn't load this profile.</p>
        ) : !p ? (
          <p className="muted">Loading…</p>
        ) : (
          <>
            {p.tile_image_url && (
              <img className="profile-tile" src={p.tile_image_url} alt="" />
            )}
            <div className="profile-head">
              <Avatar url={p.profile_image_url} name={p.display_name} />
              <div className="row-text">
                <h2>{p.display_name ?? "Unnamed"}</h2>
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

            {p.contact_email && (
              <p className="muted small">
                Contact: <a href={`mailto:${p.contact_email}`}>{p.contact_email}</a>
              </p>
            )}

            <button
              className={p.is_subscribed ? "btn btn-subscribed" : "btn btn-primary"}
              onClick={() => onToggle(!p.is_subscribed)}
            >
              {p.is_subscribed ? "Following" : "Follow"}
            </button>
          </>
        )}
      </div>
    </div>
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
            <span className="pill">{platformLabel(s.type)}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

export function Platforms({ platforms }: { platforms: string[] }) {
  if (platforms.length === 0) return <span className="muted small">no sources yet</span>;
  return (
    <span className="platforms">
      {platforms.map((p) => (
        <span key={p} className="pill">
          {p}
        </span>
      ))}
    </span>
  );
}
