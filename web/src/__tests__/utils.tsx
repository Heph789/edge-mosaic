import { render } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import type { ReactElement } from "react";
import { AuthProvider } from "../auth";
import { TOKEN_KEY, type User } from "../api";

export const API = "http://localhost:8000";

export const testUser: User = {
  id: 1,
  email: "jane@example.com",
  username: "janes",
  display_name: "Jane S.",
  digest_frequency: "weekly",
  digest_paused: false,
  onboarded: true,
  bio: null,
  contact_email: null,
  contact_phone: null,
  contact_telegram: null,
  profile_image_url: null,
  visibility: "community",
  cities: [],
  links: [],
  villages: ["EE '26"],
  edgeos_popups: [],
};

// Render a tree behind the real providers. `path` seeds the MemoryRouter; pass
// `authed` to pre-store a bearer token (callers must then mock GET /me).
export function renderWithProviders(
  ui: ReactElement,
  { path = "/", authed = false }: { path?: string; authed?: boolean } = {}
) {
  if (authed) localStorage.setItem(TOKEN_KEY, "test-token");
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[path]}>
        <AuthProvider>{ui}</AuthProvider>
      </MemoryRouter>
    </QueryClientProvider>
  );
}
