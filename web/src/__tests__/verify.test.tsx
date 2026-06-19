import { describe, expect, it } from "vitest";
import { http, HttpResponse } from "msw";
import { screen, waitFor } from "@testing-library/react";
import { AppRoutes } from "../routes";
import { server } from "./server";
import { API, renderWithProviders, testUser } from "./utils";

describe("Verify", () => {
  it("exchanges the token, stores the session, and redirects to onboarding", async () => {
    server.use(
      http.post(`${API}/auth/verify`, async ({ request }) => {
        const body = (await request.json()) as { token: string };
        expect(body.token).toBe("good-token");
        return HttpResponse.json({
          session_token: "sess-abc",
          user: { ...testUser, onboarded: false },
        });
      })
    );

    renderWithProviders(<AppRoutes />, { path: "/auth/verify?token=good-token" });

    // A not-yet-onboarded user lands on the onboarding screen.
    expect(await screen.findByText(/Welcome to Edge Mosaic/i)).toBeInTheDocument();
    expect(localStorage.getItem("em_token")).toBe("sess-abc");
  });

  it("shows an error state for an expired/invalid token", async () => {
    server.use(
      http.post(`${API}/auth/verify`, () =>
        HttpResponse.json({ detail: "This link is invalid or has expired." }, { status: 400 })
      )
    );

    renderWithProviders(<AppRoutes />, { path: "/auth/verify?token=stale" });

    expect(await screen.findByText(/Link invalid or expired/i)).toBeInTheDocument();
    await waitFor(() => expect(localStorage.getItem("em_token")).toBeNull());
  });
});
