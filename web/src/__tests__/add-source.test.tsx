import { describe, expect, it } from "vitest";
import { http, HttpResponse } from "msw";
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { AppRoutes } from "../routes";
import { server } from "./server";
import { API, renderWithProviders, testUser } from "./utils";

function meHandler() {
  return http.get(`${API}/me`, () => HttpResponse.json(testUser));
}

describe("Add source (two-step preview → confirm)", () => {
  it("previews a feed, confirms, and shows it in the list", async () => {
    const sources: unknown[] = [];
    server.use(
      meHandler(),
      http.get(`${API}/sources`, () => HttpResponse.json(sources)),
      http.post(`${API}/sources/preview`, () =>
        HttpResponse.json({
          type: "rss",
          label: "Blog",
          resolved_url: "https://blog.example.com/feed",
          title: "Example Blog",
          found_count: 7,
          latest_title: "Hello World",
          latest_published_at: "2026-06-01T00:00:00Z",
        })
      ),
      http.post(`${API}/sources`, () => {
        const source = {
          id: 42,
          type: "rss",
          label: "Blog",
          input_url: "https://blog.example.com",
          resolved_feed_url: "https://blog.example.com/feed",
          title: "Example Blog",
          last_checked_at: null,
          last_success_at: null,
          created_at: "2026-06-18T00:00:00Z",
        };
        sources.push(source);
        return HttpResponse.json(source, { status: 201 });
      })
    );

    const user = userEvent.setup();
    renderWithProviders(<AppRoutes />, { path: "/profile", authed: true });

    const input = await screen.findByPlaceholderText(/example\.com or @handle/i);
    await user.type(input, "https://blog.example.com");
    await user.click(screen.getByRole("button", { name: /^Preview$/i }));

    // Confirm card summarizes the found feed.
    expect(await screen.findByText(/found 7 recent posts/i)).toBeInTheDocument();
    expect(screen.getByText(/Hello World/)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /Add source/i }));

    // The new source appears in the list after the invalidation refetch.
    const list = await screen.findByRole("list");
    expect(await within(list).findByText("Example Blog")).toBeInTheDocument();
  });

  it("surfaces the 'coming soon' rejection for x.com inline", async () => {
    server.use(
      meHandler(),
      http.get(`${API}/sources`, () => HttpResponse.json([])),
      http.post(`${API}/sources/preview`, () =>
        HttpResponse.json({ detail: "X / Twitter support is coming soon." }, { status: 400 })
      )
    );

    const user = userEvent.setup();
    renderWithProviders(<AppRoutes />, { path: "/profile", authed: true });

    const input = await screen.findByPlaceholderText(/example\.com or @handle/i);
    await user.type(input, "https://x.com/jack");
    await user.click(screen.getByRole("button", { name: /^Preview$/i }));

    expect(
      await screen.findByText(/X \/ Twitter support is coming soon/i)
    ).toBeInTheDocument();
    // No confirm card on a rejection.
    expect(screen.queryByRole("button", { name: /Add source/i })).not.toBeInTheDocument();
  });
});
