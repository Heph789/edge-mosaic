import { describe, expect, it } from "vitest";
import { http, HttpResponse } from "msw";
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { User } from "../api";
import { AppRoutes } from "../routes";
import { server } from "./server";
import { API, renderWithProviders, testUser } from "./utils";

// A not-yet-onboarded user; PATCH /me echoes the patch back merged onto the user.
const freshUser: User = { ...testUser, display_name: null, onboarded: false };

function wizardHandlers() {
  let current: User = { ...freshUser };
  return [
    http.get(`${API}/me`, () => HttpResponse.json(current)),
    http.patch(`${API}/me`, async ({ request }) => {
      const patch = (await request.json()) as Record<string, unknown>;
      const { display_name, ...rest } = patch;
      current = {
        ...current,
        ...rest,
        ...(typeof display_name === "string"
          ? { display_name, onboarded: true }
          : {}),
      };
      return HttpResponse.json(current);
    }),
  ];
}

describe("Onboarding wizard", () => {
  it("walks the steps, saving the name then enrichment fields", async () => {
    const patches: Record<string, unknown>[] = [];
    let current: User = { ...freshUser };
    server.use(
      http.get(`${API}/me`, () => HttpResponse.json(current)),
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

    // Step 1 — name is required.
    expect(await screen.findByText(/Step 1 of 6/i)).toBeInTheDocument();
    await user.type(screen.getByPlaceholderText("Jane S."), "Chase B.");
    await user.click(screen.getByRole("button", { name: /Continue/i }));

    // Step 2 — About: fill the bio and advance.
    expect(await screen.findByText(/Step 2 of 6/i)).toBeInTheDocument();
    await user.type(screen.getByPlaceholderText(/sentence or two/i), "Builder.");
    await user.click(screen.getByRole("button", { name: /Continue/i }));

    expect(await screen.findByText(/Step 3 of 6/i)).toBeInTheDocument();

    // First PATCH set the display name; the second saved the bio.
    expect(patches[0]).toEqual({ display_name: "Chase B." });
    expect(patches[1]).toMatchObject({ bio: "Builder." });
  });

  it("requires a display name before leaving step 1", async () => {
    server.use(...wizardHandlers());
    const user = userEvent.setup();
    renderWithProviders(<AppRoutes />, { path: "/onboarding", authed: true });

    await screen.findByText(/Step 1 of 6/i);
    await user.click(screen.getByRole("button", { name: /Continue/i }));

    expect(await screen.findByText(/Please enter a display name/i)).toBeInTheDocument();
    // Still on step 1.
    expect(screen.getByText(/Step 1 of 6/i)).toBeInTheDocument();
  });
});
