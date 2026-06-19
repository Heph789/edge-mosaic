import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../auth";

// Magic-link landing. The token rides in ?token=… ; we exchange it via a deliberate POST
// (a scanner's prefetch GET only loads this JS, never burning the single-use token).
type State = "verifying" | "error";

export function Verify() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const { login } = useAuth();
  const [state, setState] = useState<State>("verifying");
  // StrictMode double-invokes effects in dev; guard so we POST the token only once.
  const ran = useRef(false);

  useEffect(() => {
    if (ran.current) return;
    ran.current = true;

    const token = params.get("token");
    if (!token) {
      setState("error");
      return;
    }
    api
      .verify(token)
      .then(({ session_token, user }) => {
        login(session_token, user);
        navigate(user.onboarded ? "/directory" : "/onboarding", { replace: true });
      })
      .catch(() => setState("error"));
  }, [params, login, navigate]);

  if (state === "verifying") {
    return (
      <div className="centered">
        <div className="card narrow">
          <p className="muted">Signing you in…</p>
        </div>
      </div>
    );
  }

  return (
    <div className="centered">
      <div className="card narrow stack">
        <h1>Link invalid or expired</h1>
        <p className="muted">
          This login link is no longer valid. Magic links are single-use and expire after a
          few minutes.
        </p>
        <Link className="btn btn-primary" to="/login">
          Request a new link
        </Link>
      </div>
    </div>
  );
}
