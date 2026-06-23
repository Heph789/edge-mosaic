// Add / list / remove feed sources. Extracted from Profile so the onboarding wizard and
// the Profile page share one implementation. Preview-then-confirm: the preview validates
// the feed, the create call re-validates server-side.
import { useState, type FormEvent } from "react";
import { api, ApiError, type SourcePreview } from "../api";
import { useAddSource, useDeleteSource, useSources } from "../hooks/queries";

type AddState =
  | { step: "idle" }
  | { step: "previewing" }
  | { step: "confirm"; preview: SourcePreview }
  | { step: "adding"; preview: SourcePreview };

export function SourcesEditor() {
  const sources = useSources();
  const addSource = useAddSource();
  const deleteSource = useDeleteSource();

  const [url, setUrl] = useState("");
  const [state, setState] = useState<AddState>({ step: "idle" });
  const [error, setError] = useState<string | null>(null);

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
      setState({ step: "idle" });
      setError(errorText(err));
    }
  }

  async function onConfirm() {
    if (state.step !== "confirm") return;
    setError(null);
    setState({ step: "adding", preview: state.preview });
    try {
      // The create call re-validates server-side; the preview was only a confirmation.
      await addSource.mutateAsync(url.trim());
      setUrl("");
      setState({ step: "idle" });
    } catch (err) {
      setState({ step: "confirm", preview: state.preview });
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
          onChange={(e) => setUrl(e.target.value)}
          onBlur={(e) => setUrl(normalizeSourceUrl(e.target.value))}
          disabled={state.step === "confirm" || state.step === "adding"}
        />
        <button
          className="btn"
          type="submit"
          disabled={state.step !== "idle" || url.trim().length === 0}
        >
          {state.step === "previewing" ? "Checking…" : "Preview"}
        </button>
      </form>

      {error && <p className="error small">{error}</p>}

      {(state.step === "confirm" || state.step === "adding") && (
        <div className="confirm-card stack">
          <div>
            <strong>{state.preview.label}</strong> — found{" "}
            {state.preview.found_count} recent{" "}
            {state.preview.found_count === 1 ? "post" : "posts"}
            {state.preview.latest_title && (
              <>
                , latest: <em>“{state.preview.latest_title}”</em>
              </>
            )}
            .
          </div>
          <div className="settings-row">
            <button
              className="btn btn-primary"
              onClick={onConfirm}
              disabled={state.step === "adding"}
            >
              {state.step === "adding" ? "Adding…" : "Add source"}
            </button>
            <button
              className="btn btn-ghost"
              onClick={onCancel}
              disabled={state.step === "adding"}
            >
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
                <span className="muted small">
                  <span className="pill">{s.label}</span> {s.input_url}
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

// Map API failures to inline copy: 400 = unsupported platform, 422 = dead/unreadable
// feed or upstream source error. Otherwise show the server message verbatim.
function errorText(err: unknown): string {
  if (err instanceof ApiError) return err.message;
  return "Something went wrong. Try again.";
}
