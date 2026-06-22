import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import type { Discover } from "../api";
import { Avatar } from "../components/ProfileView";
import { useDiscover, useToggleSubscribe } from "../hooks/queries";

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
  const navigate = useNavigate();
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
              onOpen={() => navigate(`/p/${row.username}`)}
              onToggle={() =>
                toggle.mutate({ userId: row.user_id, subscribe: !row.is_subscribed })
              }
            />
          ))}
        </ul>
      )}
    </div>
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
