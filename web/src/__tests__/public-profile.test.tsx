import { describe, expect, it } from "vitest";
import { http, HttpResponse } from "msw";
import { screen } from "@testing-library/react";
import { AppRoutes } from "../routes";
import { server } from "./server";
import { API, renderWithProviders, testUser } from "./utils";

describe("PublicProfile page", () => {
  it("shows an error when the profile is hidden or missing", async () => {
    server.use(
      http.get(`${API}/me`, () => HttpResponse.json(testUser)),
      http.get(`${API}/users/by-username/ghost`, () =>
        HttpResponse.json({ detail: "profile not found" }, { status: 404 })
      )
    );

    renderWithProviders(<AppRoutes />, { path: "/p/ghost", authed: true });
    expect(
      await screen.findByText(/doesn't exist or isn't visible/i)
    ).toBeInTheDocument();
  });
});
