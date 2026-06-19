import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { ApiError } from "../api";
import { useAuth } from "../auth";
import { useUpdateMe } from "../hooks/queries";

// One-field onboarding: confirm/edit the display name (may be a preseeded "Jane S.").
// PATCH /me with a display_name flips `onboarded` server-side; then we head to the app.
export function Onboarding() {
  const { user, applyUser } = useAuth();
  const navigate = useNavigate();
  const [name, setName] = useState(user?.display_name ?? "");
  const [error, setError] = useState<string | null>(null);
  const updateMe = useUpdateMe((fresh) => {
    applyUser(fresh);
    navigate("/directory", { replace: true });
  });

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    const trimmed = name.trim();
    if (!trimmed) {
      setError("Please enter a display name.");
      return;
    }
    try {
      await updateMe.mutateAsync({ display_name: trimmed });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't save — try again.");
    }
  }

  return (
    <div className="centered">
      <div className="card narrow stack">
        <h1>Welcome to Edge Mosaic</h1>
        <p className="muted">
          What name should appear on your digests and in the Directory?
        </p>
        <form onSubmit={onSubmit} className="stack">
          <label className="field">
            <span>Display name</span>
            <input
              autoFocus
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Jane S."
            />
          </label>
          {error && <p className="error">{error}</p>}
          <button className="btn btn-primary" type="submit" disabled={updateMe.isPending}>
            {updateMe.isPending ? "Saving…" : "Continue"}
          </button>
        </form>
      </div>
    </div>
  );
}
