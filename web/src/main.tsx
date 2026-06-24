import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import {
  MutationCache,
  QueryCache,
  QueryClient,
  QueryClientProvider,
} from "@tanstack/react-query";
import { BrowserRouter } from "react-router-dom";
import * as Sentry from "@sentry/react";
import { AuthProvider } from "./auth";
import { AppRoutes } from "./routes";
import { initSentry, reportError } from "./sentry";
import "./index.css";

initSentry();

// Every query/mutation error funnels through reportError, our single Sentry choke
// point. This is what guarantees a failed "add source" or "subscribe" is captured —
// even the subscribe toggle, which silently rolls back its optimistic update and
// shows the user nothing. reportError drops expected 4xx ApiErrors, so only real
// failures (5xx, network, unexpected throws) reach Sentry.
const queryClient = new QueryClient({
  defaultOptions: {
    queries: { retry: false, refetchOnWindowFocus: false },
  },
  queryCache: new QueryCache({
    onError: (error, query) =>
      reportError(error, { kind: "query", queryKey: query.queryKey }),
  }),
  mutationCache: new MutationCache({
    onError: (error, _vars, _ctx, mutation) =>
      reportError(error, { kind: "mutation", operation: mutation.options.meta?.operation }),
  }),
});

function AppCrash() {
  return (
    <div className="page stack">
      <h1>Something went wrong</h1>
      <p className="muted">
        The app hit an unexpected error and the team has been notified. Try reloading the page.
      </p>
      <button className="btn btn-primary" onClick={() => window.location.reload()}>
        Reload
      </button>
    </div>
  );
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <Sentry.ErrorBoundary fallback={<AppCrash />}>
      <QueryClientProvider client={queryClient}>
        <BrowserRouter>
          <AuthProvider>
            <AppRoutes />
          </AuthProvider>
        </BrowserRouter>
      </QueryClientProvider>
    </Sentry.ErrorBoundary>
  </StrictMode>
);
