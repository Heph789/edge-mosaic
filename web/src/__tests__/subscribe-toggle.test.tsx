import { describe, expect, it } from "vitest";
import { delay, http, HttpResponse } from "msw";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { AppRoutes } from "../routes";
import { server } from "./server";
import { API, renderWithProviders, testUser } from "./utils";

const meHandler = () => http.get(`${API}/me`, () => HttpResponse.json(testUser));

describe("Directory subscribe toggle", () => {
  it("optimistically flips to Following on a successful subscribe", async () => {
    let subscribed = false;
    server.use(
      meHandler(),
      http.get(`${API}/discover`, () =>
        HttpResponse.json([
          { user_id: 2, display_name: "Bob R.", platforms: ["rss"], is_subscribed: subscribed },
        ])
      ),
      http.post(`${API}/subscriptions`, () => {
        subscribed = true;
        return HttpResponse.json({ feeder_id: 2, display_name: "Bob R.", platforms: ["rss"] });
      })
    );

    const user = userEvent.setup();
    renderWithProviders(<AppRoutes />, { path: "/directory", authed: true });

    const search = await screen.findByPlaceholderText(/Filter people/i);
    await user.type(search, "bob");

    const follow = await screen.findByRole("button", { name: /^Follow$/i });
    await user.click(follow);

    expect(await screen.findByRole("button", { name: /Following/i })).toBeInTheDocument();
  });

  it("rolls back to Follow when the subscribe request fails", async () => {
    server.use(
      meHandler(),
      http.get(`${API}/discover`, () =>
        HttpResponse.json([
          { user_id: 2, display_name: "Bob R.", platforms: ["rss"], is_subscribed: false },
        ])
      ),
      http.post(`${API}/subscriptions`, async () => {
        // Hold the response so the optimistic "Following" state is observable before rollback.
        await delay(50);
        return HttpResponse.json({ detail: "boom" }, { status: 500 });
      })
    );

    const user = userEvent.setup();
    renderWithProviders(<AppRoutes />, { path: "/directory", authed: true });

    const search = await screen.findByPlaceholderText(/Filter people/i);
    await user.type(search, "bob");

    const follow = await screen.findByRole("button", { name: /^Follow$/i });
    await user.click(follow);

    // Optimistic flip, then rollback once the server rejects.
    expect(await screen.findByRole("button", { name: /Following/i })).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /^Follow$/i })).toBeInTheDocument()
    );
  });
});
