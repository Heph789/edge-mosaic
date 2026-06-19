import { useEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api } from "../api";

// One-click unsubscribe landing. POST the token (anti-prefetch); the API returns a generic
// confirmation regardless of token validity, so we just show it.
type State = "working" | "done" | "error";

export function Unsubscribe() {
  const [params] = useSearchParams();
  const [state, setState] = useState<State>("working");
  const [message, setMessage] = useState("");
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
      .unsubscribe(token)
      .then((res) => {
        setMessage(res.message);
        setState("done");
      })
      .catch(() => setState("error"));
  }, [params]);

  return (
    <div className="centered">
      <div className="card narrow stack">
        {state === "working" && <p className="muted">Processing your request…</p>}
        {state === "done" && (
          <>
            <h1>You're unsubscribed</h1>
            <p className="muted">{message}</p>
            <p className="muted">
              You can re-enable digests anytime from the Digest tab after logging in.
            </p>
            <Link className="btn" to="/login">
              Go to Edge Mosaic
            </Link>
          </>
        )}
        {state === "error" && (
          <>
            <h1>Something went wrong</h1>
            <p className="muted">
              We couldn't process that unsubscribe link. It may be malformed.
            </p>
            <Link className="btn" to="/login">
              Go to Edge Mosaic
            </Link>
          </>
        )}
      </div>
    </div>
  );
}
