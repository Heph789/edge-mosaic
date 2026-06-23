// Sentry browser monitoring. Errors-only (no tracing / no replay) to stay light.
//
// The DSN comes from VITE_SENTRY_DSN. When it's unset — local dev, or a preview
// build without the var — init() is a no-op and every helper below degrades to a
// safe no-op too (Sentry's API tolerates being called before/without init). That
// keeps dev errors out of Sentry; set the var in Vercel to enable the deployed app.
import * as Sentry from "@sentry/react";
import { ApiError } from "./api";

// 4xx ApiErrors are *expected*, handled UX states — rejected platform (400),
// dead/unreadable feed (422), validation (422), session expired (401). The UI
// already surfaces these; they are not bugs. We only want Sentry to fire on the
// genuine problems: 5xx responses, network failures, and non-ApiError throws
// (render crashes, unexpected exceptions).
function isExpected(err: unknown): boolean {
  return err instanceof ApiError && err.status >= 400 && err.status < 500;
}

export function initSentry(): void {
  const dsn = import.meta.env.VITE_SENTRY_DSN;
  if (!dsn) return; // no DSN → stay silent (local dev / preview)

  Sentry.init({
    dsn,
    environment: import.meta.env.MODE,
    // Don't auto-attach IP / cookies / request bodies. We set user context
    // explicitly (id + email) in auth.tsx for debuggability.
    sendDefaultPii: false,
    // Final safety net: drop expected, handled API states even if something
    // reports them directly (e.g. the ErrorBoundary path).
    beforeSend(event, hint) {
      if (isExpected(hint?.originalException)) return null;
      return event;
    },
  });
}

// Forward an error to Sentry unless it's an expected/handled API state. This is
// the single choke point used by the React Query caches in main.tsx, so the
// "add source" and "subscribe" mutation failures both flow through here.
export function reportError(error: unknown, context?: Record<string, unknown>): void {
  if (isExpected(error)) return;
  Sentry.captureException(error, context ? { extra: context } : undefined);
}

// Attach (or clear) the signed-in user so events are attributable. Called from
// auth.tsx on login, cold-load hydrate, and logout.
export function setSentryUser(user: { id: number; email: string } | null): void {
  Sentry.setUser(user ? { id: String(user.id), email: user.email } : null);
}

// --- onboarding funnel ---------------------------------------------------------------
// Errors-only Sentry isn't a funnel tool, so we emit our own lightweight step events:
// an info-level breadcrumb + message tagged with the step and a per-run session id. The
// last "view" event a session produced is where that user dropped off. `phase` is "view"
// when a step is shown and "complete" when the user advances past it (or finishes). When
// the DSN is unset (local dev), these degrade to no-ops like every other helper here.
export function trackOnboardingStep(
  step: string,
  phase: "view" | "complete",
  sessionId: string
): void {
  const tags = { onboarding_session: sessionId, onboarding_step: step, onboarding_phase: phase };
  Sentry.addBreadcrumb({
    category: "onboarding",
    message: `${phase}: ${step}`,
    level: "info",
    data: tags,
  });
  Sentry.captureMessage(`onboarding ${phase}: ${step}`, { level: "info", tags });
}
