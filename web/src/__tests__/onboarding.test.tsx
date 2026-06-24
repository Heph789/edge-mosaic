import { describe, expect, it } from "vitest";
import { http, HttpResponse } from "msw";
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { User } from "../api";
import { AppRoutes } from "../routes";
import { server } from "./server";
import { API, renderWithProviders, testUser } from "./utils";

// A not-yet-onboarded user: display_name unset, username still the auto placeholder.
const freshUser: User = {
  ...testUser,
  username: "user-1",
  display_name: null,
  onboarded: false,
};

// Every username the wizard checks is reported free.
const availableHandler = http.get(`${API}/usernames/:username/available`, () =>
  HttpResponse.json({ valid: true, available: true })
);

describe("Onboarding wizard", () => {
  it("walks the steps, saving the name + username then enrichment fields", async () => {
    const patches: Record<string, unknown>[] = [];
    let current: User = { ...freshUser };
    server.use(
      availableHandler,
      http.get(`${API}/me`, () => HttpResponse.json(current)),
      http.get(`${API}/sources`, () => HttpResponse.json([])),
      http.patch(`${API}/me`, async ({ request }) => {
        const patch = (await request.json()) as Record<string, unknown>;
        patches.push(patch);
        const { display_name, ...rest } = patch;
        current = {
          ...current,
          ...rest,
          ...(typeof display_name === "string"
            ? { display_name, onboarded: true }
            : {}),
        };
        return HttpResponse.json(current);
      })
    );

    const user = userEvent.setup();
    renderWithProviders(<AppRoutes />, { path: "/onboarding", authed: true });

    // Step 1 — display name + username are required.
    expect(await screen.findByText(/Step 1 of 4/i)).toBeInTheDocument();
    await user.type(screen.getByPlaceholderText("Jane S."), "Chase B.");
    const handle = screen.getByPlaceholderText("janes");
    await user.clear(handle);
    await user.type(handle, "chaseb");
    await user.click(screen.getByRole("button", { name: /Continue/i }));

    // Step 2 — About: fill the bio and advance.
    expect(await screen.findByText(/Step 2 of 4/i)).toBeInTheDocument();
    await user.type(screen.getByPlaceholderText(/sentence or two/i), "Builder.");
    await user.click(screen.getByRole("button", { name: /Continue/i }));

    expect(await screen.findByText(/Step 3 of 4/i)).toBeInTheDocument();

    // First PATCH set the display name + chosen username; the second saved the bio.
    expect(patches[0]).toEqual({ display_name: "Chase B.", username: "chaseb" });
    expect(patches[1]).toMatchObject({ bio: "Builder." });
  });
});
