// Add / list / remove feed sources. Extracted from Profile so the onboarding wizard and
// the Profile page share one implementation. Preview-then-confirm validates the feed
// synchronously; if it can't be read we don't block — the source is still added (as
// 'unverified') so it shows on the profile with a warning, just not in followers' digests.
import { useState, type FormEvent } from "react";
import { api, ApiError, type SourcePreview } from "../api";
import { useAddSource, useDeleteSource, useSources } from "../hooks/queries";
import { UnverifiedBadge } from "./UnverifiedBadge";

type AddState =
  | { step: "idle" }
  | { step: "previewing" }
  | { step: "confirm"; preview: SourcePreview }
  // Preview couldn't read a feed. The user can still add it — same "Add source" action,
  // it just lands as 'unverified'.
  | { step: "warn"; message: string }
  | { step: "adding" };

export function SourcesEditor() {
  const sources = useSources();
  const addSource = useAddSource();
  const deleteSource = useDeleteSource();

  const [url, setUrl] = useState("");
  const [state, setState] = useState<AddState>({ step: "idle" });
  const [error, setError] = useState<string | null>(null);

  const busy = state.step === "previewing" || state.step === "adding";
  const substackProfile = isSubstackProfileUrl(url);

  async function onPreview(e: FormEvent) {
    e.preventDefault();
    setError(null);
    const trimmed = url.trim();
    if (!trimmed) return;
    setState({ step: "previewing" });
    try {
      const preview = await api.previewSource(trimmed);
      setState({ step: "confirm", preview });
    } catch (err) {
      // Couldn't read a feed — don't dead-end the user. Offer to add it anyway (unverified).
      setState({ step: "warn", message: errorText(err) });
    }
  }

  async function onAdd() {
    if (state.step !== "confirm" && state.step !== "warn") return;
    setError(null);
    setState({ step: "adding" });
    try {
      // The create call re-validates server-side; a readable feed lands 'active', an
      // unreadable one lands 'unverified' (never an error).
      await addSource.mutateAsync(url.trim());
      setUrl("");
      setState({ step: "idle" });
    } catch (err) {
      // Only genuine failures (network / 5xx) reach here now.
      setState({ step: "warn", message: errorText(err) });
      setError(errorText(err));
    }
  }

  function onCancel() {
    setState({ step: "idle" });
    setError(null);
  }

  return (
    <div className="stack">
      <p className="muted small">
        Paste a blog/Substack RSS URL, a Bluesky handle, or an X profile.
      </p>

      <form onSubmit={onPreview} className="settings-row">
        <input
          placeholder="https://example.com, @handle.bsky.social, or x.com/username"
          value={url}
          onChange={(e) => {
            setUrl(e.target.value);
            if (state.step === "warn" || state.step === "confirm") setState({ step: "idle" });
          }}
          onBlur={(e) => setUrl(normalizeSourceUrl(e.target.value))}
          disabled={busy}
        />
        <button className="btn" type="submit" disabled={busy || url.trim().length === 0}>
          {state.step === "previewing" ? "Checking…" : "Preview"}
        </button>
      </form>

      {/* Substack profile → publication hint, detectable client-side as they type. */}
      {substackProfile && (
        <p className="muted small">
          That looks like a Substack <strong>profile</strong>. To pull your posts, paste your{" "}
          <strong>publication</strong> URL instead — it looks like{" "}
          <code>yourname.substack.com</code>.
        </p>
      )}

      {error && <p className="error small">{error}</p>}

      {state.step === "confirm" && (
        <div className="confirm-card stack">
          <div>
            <strong>{state.preview.label}</strong> — found {state.preview.found_count} recent{" "}
            {state.preview.found_count === 1 ? "post" : "posts"}
            {state.preview.latest_title && (
              <>
                , latest: <em>“{state.preview.latest_title}”</em>
              </>
            )}
            .
          </div>
          <div className="settings-row">
            <button className="btn btn-primary" onClick={onAdd}>
              Add source
            </button>
            <button className="btn btn-ghost" onClick={onCancel}>
              Cancel
            </button>
          </div>
        </div>
      )}

      {state.step === "warn" && (
        <div className="confirm-card confirm-card--warn stack">
          <div>
            <strong>⚠ We couldn't read a feed from that link yet.</strong>
            <p className="muted small">
              You can still add it — it'll show on your profile, but won't appear in your
              followers' digests until we can scrape it.
            </p>
          </div>
          <div className="settings-row">
            <button className="btn btn-primary" onClick={onAdd}>
              Add source
            </button>
            <button className="btn btn-ghost" onClick={onCancel}>
              Cancel
            </button>
          </div>
        </div>
      )}

      {sources.isLoading ? (
        <p className="muted">Loading…</p>
      ) : sources.data && sources.data.length === 0 ? (
        <p className="muted">No sources yet.</p>
      ) : (
        <ul className="list">
          {sources.data?.map((s) => (
            <li className="row" key={s.id}>
              <div className="row-main">
                <span className="row-name">{s.title ?? s.input_url}</span>
                <span className="muted small source-meta">
                  <span className="pill">{s.label}</span>
                  {s.status === "unverified" && <UnverifiedBadge />}
                  <span className="source-url">{s.input_url}</span>
                </span>
              </div>
              <button
                className="btn btn-ghost"
                disabled={deleteSource.isPending}
                onClick={() => deleteSource.mutate(s.id)}
              >
                Remove
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

// Mirrors api/app/sources.py `normalize_source_url`: default a scheme-less feed URL to
// https:// so the resolver fetches a URL, not a path. Bluesky @handles pass through.
function normalizeSourceUrl(url: string): string {
  const trimmed = url.trim();
  if (!trimmed || trimmed.startsWith("@") || trimmed.includes("://")) return trimmed;
  return `https://${trimmed}`;
}

// A Substack *profile* (substack.com/@handle or /profile/…) can't be scraped — only a
// *publication* (yourname.substack.com) has a feed. Detected client-side so we can nudge
// the user before they even submit.
function isSubstackProfileUrl(raw: string): boolean {
  const trimmed = raw.trim();
  if (!trimmed || trimmed.startsWith("@")) return false;
  try {
    const u = new URL(trimmed.includes("://") ? trimmed : `https://${trimmed}`);
    const host = u.hostname.toLowerCase().replace(/^www\./, "");
    if (host !== "substack.com") return false; // a publication is *.substack.com → fine
    return u.pathname.startsWith("/@") || u.pathname.startsWith("/profile");
  } catch {
    return false;
  }
}

// Map API failures to inline copy. With the new add behavior the create call no longer 422s
// on a dead feed, so this is only hit by preview failures and genuine errors.
function errorText(err: unknown): string {
  if (err instanceof ApiError) return err.message;
  return "Something went wrong. Try again.";
}
