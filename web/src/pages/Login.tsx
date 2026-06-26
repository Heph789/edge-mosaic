import { useState, type FormEvent } from "react";
import { api } from "../api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

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
    <div className="grid h-full place-items-center px-5">
      <div className="w-full max-w-sm rounded-2xl border border-border bg-card p-7 shadow-sm">
        <p className="font-mono text-[10px] uppercase tracking-[0.18em] text-faint">
          Welcome to
        </p>
        <h1 className="mb-5 font-display text-3xl font-bold tracking-tight">
          Edge Mosaic
        </h1>
        {sent ? (
          <p className="text-muted-foreground" role="status">
            If your email is eligible, a login link is on its way. Check your inbox. If you're having trouble, message @chaselb on telegram.
          </p>
        ) : (
          <form onSubmit={onSubmit} className="flex flex-col gap-4">
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
            <Button type="submit" disabled={submitting} className="w-full">
              {submitting ? "Sending…" : "Send me a login link"}
            </Button>
          </form>
        )}
      </div>
    </div>
  );
}
