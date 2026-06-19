import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { api, ApiError, type SourcePreview } from "../api";
import { useAuth } from "../auth";
import { useAddSource, useDeleteSource, useSources, useUpdateMe } from "../hooks/queries";

export function Profile() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();

  async function handleLogout() {
    await logout();
    navigate("/login", { replace: true });
  }

  return (
    <div className="page stack">
      <div className="page-head">
        <h1>Profile</h1>
        <button className="btn btn-ghost" onClick={handleLogout}>
          Log out
        </button>
      </div>
      <p className="muted small">{user?.email}</p>

      <DisplayNameSection />
      <SourcesSection />
    </div>
  );
}

function DisplayNameSection() {
  const { user, applyUser } = useAuth();
  const [name, setName] = useState(user?.display_name ?? "");
  const [status, setStatus] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const updateMe = useUpdateMe((fresh) => {
    applyUser(fresh);
    setStatus("Saved.");
  });

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setStatus(null);
    setError(null);
    const trimmed = name.trim();
    if (!trimmed) {
      setError("Display name can't be empty.");
      return;
    }
    try {
      await updateMe.mutateAsync({ display_name: trimmed });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't save — try again.");
    }
  }

  return (
    <section className="card stack">
      <h2>Display name</h2>
      <form onSubmit={onSubmit} className="settings-row">
        <input
          value={name}
          onChange={(e) => {
            setName(e.target.value);
            setStatus(null);
          }}
        />
        <button className="btn btn-primary" type="submit" disabled={updateMe.isPending}>
          {updateMe.isPending ? "Saving…" : "Save"}
        </button>
      </form>
      {status && <p className="success small">{status}</p>}
      {error && <p className="error small">{error}</p>}
    </section>
  );
}

type AddState =
  | { step: "idle" }
  | { step: "previewing" }
  | { step: "confirm"; preview: SourcePreview }
  | { step: "adding"; preview: SourcePreview };

function SourcesSection() {
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
    <section className="card stack">
      <h2>Your sources</h2>
      <p className="muted small">
        Paste a blog/Substack RSS URL or a Bluesky handle. (X / Twitter coming soon.)
      </p>

      <form onSubmit={onPreview} className="settings-row">
        <input
          placeholder="https://example.com or @handle.bsky.social"
          value={url}
          onChange={(e) => setUrl(e.target.value)}
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
            <strong>{platformLabel(state.preview.type)}</strong> — found{" "}
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
            <button className="btn btn-ghost" onClick={onCancel} disabled={state.step === "adding"}>
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
                  <span className="pill">{platformLabel(s.type)}</span> {s.input_url}
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
    </section>
  );
}

function platformLabel(type: string): string {
  if (type === "rss") return "RSS";
  if (type === "bluesky") return "Bluesky";
  return type;
}

// Map API failures to inline copy: 400 = rejected platform (x.com "coming soon"),
// 422 = dead/unreadable feed. Otherwise show the server message verbatim.
function errorText(err: unknown): string {
  if (err instanceof ApiError) return err.message;
  return "Something went wrong. Try again.";
}
