import { describe, expect, it } from "vitest";
import { http, HttpResponse } from "msw";
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { PublicProfile } from "../api";
import { AppRoutes } from "../routes";
import { server } from "./server";
import { API, renderWithProviders, testUser } from "./utils";

const profile: PublicProfile = {
  id: 7,
  username: "chaseb",
  display_name: "Chase B.",
  bio: "Builder.",
  contact_email: null,
  contact_telegram: null,
  profile_image_url: null,
  tile_image_url: null,
  cities: ["Austin"],
  links: [],
  platforms: [],
  sources: [],
  is_subscribed: false,
};

describe("PublicProfile page", () => {
  it("renders a profile at /p/:username and follows", async () => {
    let subscribed: number | null = null;
    server.use(
      http.get(`${API}/me`, () => HttpResponse.json(testUser)),
      http.get(`${API}/users/by-username/chaseb`, () => HttpResponse.json(profile)),
      http.post(`${API}/subscriptions`, async ({ request }) => {
        const body = (await request.json()) as { feeder_id: number };
        subscribed = body.feeder_id;
        return HttpResponse.json({ feeder_id: body.feeder_id, display_name: "Chase B.", platforms: [] });
      })
    );

    const user = userEvent.setup();
    renderWithProviders(<AppRoutes />, { path: "/p/chaseb", authed: true });

    expect(await screen.findByRole("heading", { name: "Chase B." })).toBeInTheDocument();
    expect(screen.getByText("@chaseb")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /^Follow$/i }));
    expect(subscribed).toBe(7);
  });

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
