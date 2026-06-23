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
          status: "active",
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

    const input = await screen.findByPlaceholderText(/example\.com.*@handle/i);
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

  it("previews and adds an X profile, showing the X platform pill", async () => {
    const sources: unknown[] = [];
    server.use(
      meHandler(),
      http.get(`${API}/sources`, () => HttpResponse.json(sources)),
      http.post(`${API}/sources/preview`, () =>
        HttpResponse.json({
          type: "x",
          label: "X",
          resolved_url: "https://x.com/jack",
          title: "jack",
          found_count: 3,
          latest_title: null,
          latest_published_at: "2026-06-20T00:00:00Z",
        })
      ),
      http.post(`${API}/sources`, () => {
        const source = {
          id: 7,
          type: "x",
          label: "X",
          input_url: "https://x.com/jack",
          resolved_feed_url: null,
          title: "jack",
          status: "active",
          last_checked_at: null,
          last_success_at: null,
          created_at: "2026-06-20T00:00:00Z",
        };
        sources.push(source);
        return HttpResponse.json(source, { status: 201 });
      })
    );

    const user = userEvent.setup();
    renderWithProviders(<AppRoutes />, { path: "/profile", authed: true });

    const input = await screen.findByPlaceholderText(/example\.com.*x\.com/i);
    await user.type(input, "https://x.com/jack");
    await user.click(screen.getByRole("button", { name: /^Preview$/i }));

    // Confirm card shows the X platform label, not the raw type.
    expect(await screen.findByText(/found 3 recent posts/i)).toBeInTheDocument();
    expect(screen.getByText("X")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /Add source/i }));

    const list = await screen.findByRole("list");
    expect(await within(list).findByText("jack")).toBeInTheDocument();
    expect(within(list).getByText("X")).toBeInTheDocument();
  });
});
