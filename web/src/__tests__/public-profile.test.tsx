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

  it("folds an unscrapable source into Links instead of flagging it in Feeds", async () => {
    server.use(
      http.get(`${API}/me`, () => HttpResponse.json(testUser)),
      http.get(`${API}/users/by-username/kai`, () =>
        HttpResponse.json({
          id: 2,
          username: "kai",
          display_name: "Kai",
          bio: null,
          contact_email: null,
          contact_telegram: null,
          profile_image_url: null,
          cities: [],
          links: [{ label: "site", url: "https://kai.example" }],
          platforms: [],
          sources: [
            {
              type: "rss",
              label: "Substack",
              url: "https://kai.substack.com",
              title: "Kai's Substack",
              status: "active",
            },
            {
              type: "rss",
              label: "YouTube",
              url: "https://youtube.com/kai",
              title: "Kai's YouTube",
              status: "unverified",
            },
          ],
          is_subscribed: false,
          verified: true,
          has_email: true,
        })
      )
    );

    renderWithProviders(<AppRoutes />, { path: "/p/kai", authed: true });

    expect(await screen.findByText("Kai's Substack")).toBeInTheDocument();
    expect(screen.getByText("Kai's YouTube")).toBeInTheDocument();
    expect(screen.queryByText(/unverified/i)).not.toBeInTheDocument();
  });
});
