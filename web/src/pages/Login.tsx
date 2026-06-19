import { useState, type FormEvent } from "react";
import { api } from "../api";

// Privacy-preserving login: we POST the email and ALWAYS show the same generic message,
// whether or not the address is on the allowlist (§2 — never reveal membership).
export function Login() {
  const [email, setEmail] = useState("");
  const [sent, setSent] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    try {
      await api.requestLink(email);
    } catch {
      /* swallow — never reveal anything about this address */
    } finally {
      setSubmitting(false);
      setSent(true);
    }
  }

  return (
    <div className="centered">
      <div className="card narrow">
        <h1>Edge Mosaic</h1>
        {sent ? (
          <p className="muted" role="status">
            If your email is eligible, a login link is on its way. Check your inbox.
          </p>
        ) : (
          <form onSubmit={onSubmit} className="stack">
            <label className="field">
              <span>Edge email</span>
              <input
                type="email"
                required
                autoFocus
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="you@example.com"
              />
            </label>
            <button className="btn btn-primary" type="submit" disabled={submitting}>
              {submitting ? "Sending…" : "Send me a login link"}
            </button>
          </form>
        )}
      </div>
    </div>
  );
}
