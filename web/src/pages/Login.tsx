import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { api, ApiError } from "../api";
import { useAuth } from "../auth";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

// Privacy-preserving login (§2 — never reveal eligibility). One email field; the API
// routes it: legacy accounts get a magic link ("link-sent"), everyone else the EdgeOS
// 6-digit OTP ("code"). Within a mode the response is identical whether or not the email
// is eligible — an ineligible address just never receives anything.
type Phase = "email" | "link-sent" | "code";

export function Login() {
  const navigate = useNavigate();
  const { login } = useAuth();
  const [phase, setPhase] = useState<Phase>("email");
  const [email, setEmail] = useState("");
  const [code, setCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function onSubmitEmail(e: FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      const { mode } = await api.startLogin(email);
      setPhase(mode === "code" ? "code" : "link-sent");
    } catch (err) {
      if (err instanceof ApiError && err.status === 503) {
        setError(err.message); // EdgeOS briefly down — retryable, not an eligibility leak
      } else {
        setPhase("link-sent"); // swallow — never reveal anything about this address
      }
    } finally {
      setSubmitting(false);
    }
  }

  async function onSubmitCode(e: FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      const { session_token, user } = await api.verifyEdgeosCode(email, code);
      login(session_token, user);
      navigate(user.onboarded ? "/directory" : "/onboarding", { replace: true });
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.message
          : "Something went wrong. Please try again."
      );
      setSubmitting(false);
    }
  }

  function reset() {
    setPhase("email");
    setCode("");
    setError(null);
  }

  return (
    <div className="grid h-full place-items-center px-5">
      <div className="w-full max-w-sm rounded-2xl border border-border bg-card p-7 shadow-sm">
        <p className="font-mono text-[10px] lg:text-[12px] uppercase tracking-[0.18em] text-faint">
          Welcome to
        </p>
        <h1 className="mb-5 font-display text-3xl font-bold tracking-tight">
          Edge Mosaic
        </h1>
        {phase === "link-sent" ? (
          <p className="text-muted-foreground" role="status">
            If your email is eligible, a login link is on its way. Check your inbox. If you're having trouble, message @chaselb on telegram.
          </p>
        ) : phase === "code" ? (
          <form onSubmit={onSubmitCode} className="flex flex-col gap-4">
            <p className="text-muted-foreground" role="status">
              If your email is eligible, EdgeOS is sending a 6-digit code to{" "}
              <span className="text-foreground">{email}</span>. Enter it below.
            </p>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="login-code">6-digit code</Label>
              <Input
                id="login-code"
                inputMode="numeric"
                autoComplete="one-time-code"
                pattern="\d{6}"
                maxLength={6}
                required
                autoFocus
                value={code}
                onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))}
                placeholder="123456"
              />
            </div>
            {error && (
              <p className="text-sm text-destructive" role="alert">
                {error}
              </p>
            )}
            <Button type="submit" disabled={submitting || code.length !== 6} className="w-full">
              {submitting ? "Signing in…" : "Sign in"}
            </Button>
            <button
              type="button"
              onClick={reset}
              className="text-sm text-muted-foreground underline-offset-4 hover:underline"
            >
              Use a different email
            </button>
          </form>
        ) : (
          <form onSubmit={onSubmitEmail} className="flex flex-col gap-4">
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="login-email">Edge email</Label>
              <Input
                id="login-email"
                type="email"
                required
                autoFocus
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="you@example.com"
              />
            </div>
            {error && (
              <p className="text-sm text-destructive" role="alert">
                {error}
              </p>
            )}
            <Button type="submit" disabled={submitting} className="w-full">
              {submitting ? "Sending…" : "Continue"}
            </Button>
          </form>
        )}
      </div>
    </div>
  );
}
