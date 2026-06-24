import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, ApiError, type Link, type MePatch, type Visibility } from "../api";
import { useAuth } from "../auth";
import { useSources, useUpdateMe } from "../hooks/queries";
import {
  BioField,
  CitiesEditor,
  ContactFields,
  Field,
  ImageUploader,
  isValidEmail,
  isValidPhone,
  isValidTelegram,
  LinksEditor,
  VisibilityToggle,
} from "../components/ProfileFields";
import { SourcesEditor } from "../components/SourcesEditor";
import { trackOnboardingStep } from "../sentry";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

// Multi-step onboarding wizard. Step 1 (display name) flips `onboarded` via PATCH /me;
// /onboarding lives outside the RequireOnboarded guard, so later enrichment steps don't
// bounce the user. Every step is skippable except the name. Finish → the app.
// Sources & Links are merged into one step; feeders auto-verify on input so Continue stays
// blocked until at least one source is confirmed.
const STEPS = ["Name", "About you", "Sources & Links", "Visibility"] as const;

export function Onboarding() {
  const { user, applyUser } = useAuth();
  const navigate = useNavigate();
  const [step, setStep] = useState(0);
  const [error, setError] = useState<string | null>(null);

  // Local form state for the text/list fields, seeded from the current user.
  const [name, setName] = useState(user?.display_name ?? "");
  const [username, setUsername] = useState(user?.username ?? "");
  const usernameStatus = useUsernameAvailability(username);
  const [bio, setBio] = useState(user?.bio ?? "");
  const [cities, setCities] = useState<string[]>(user?.cities ?? []);
  // Pre-fill the public contact email with the sign-in email; the field has a clear button.
  const [contactEmail, setContactEmail] = useState(
    user?.contact_email ?? user?.email ?? ""
  );
  const [contactPhone, setContactPhone] = useState(user?.contact_phone ?? "");
  const [contactTelegram, setContactTelegram] = useState(user?.contact_telegram ?? "");
  const [links, setLinks] = useState<Link[]>(user?.links ?? []);
  const [visibility, setVisibility] = useState<Visibility>(user?.visibility ?? "community");
  // Surface the "name required" message only after a failed Continue, so it doesn't nag
  // before the user has typed anything.
  const [nameTouched, setNameTouched] = useState(false);

  const updateMe = useUpdateMe(applyUser);
  const sources = useSources();
  const [sourcesVerifying, setSourcesVerifying] = useState(false);
  const last = step === STEPS.length - 1;

  // A stable id for this onboarding run so Sentry can stitch the step events into a funnel.
  const sessionId = useRef<string>(crypto.randomUUID()).current;
  // Fire a "view" event whenever a step is shown — the last one a session emits marks where
  // the user dropped off.
  useEffect(() => {
    trackOnboardingStep(STEPS[step], "view", sessionId);
  }, [step, sessionId]);

  // --- inline validation -----------------------------------------------------------------
  const nameError = !name.trim() ? "Please enter a display name." : null;
  const usernameError =
    !username.trim()
      ? "Please choose a username."
      : usernameStatus === "invalid"
        ? "3–30 characters: letters, numbers, - or _."
        : usernameStatus === "taken"
          ? "That username is already taken."
          : null;
  const nameStepValid = !nameError && !usernameError;
  const aboutValid =
    isValidEmail(contactEmail) && isValidPhone(contactPhone) && isValidTelegram(contactTelegram);
  const sourcesBlocked =
    STEPS[step] === "Sources & Links" &&
    (sourcesVerifying || (sources.data?.length ?? 0) === 0);
  const continueDisabled =
    updateMe.isPending ||
    sourcesBlocked ||
    (STEPS[step] === "Name" && !nameStepValid) ||
    (STEPS[step] === "About you" && !aboutValid);

  // Persist the fields owned by the current step, then advance (or finish).
  async function saveAndNext(patch: MePatch) {
    setError(null);
    try {
      if (Object.keys(patch).length > 0) await updateMe.mutateAsync(patch);
      trackOnboardingStep(STEPS[step], "complete", sessionId);
      if (last) {
        trackOnboardingStep("Finished", "complete", sessionId);
        navigate("/directory", { replace: true });
      } else setStep((s) => s + 1);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't save — try again.");
    }
  }

  function onNext() {
    switch (STEPS[step]) {
      case "Name": {
        setNameTouched(true);
        if (!nameStepValid) return;
        return saveAndNext({
          display_name: name.trim(),
          username: username.trim().toLowerCase(),
        });
      }
      case "About you": {
        if (!aboutValid) return;
        return saveAndNext({
          bio: bio.trim(),
          cities: cities.map((c) => c.trim()).filter(Boolean),
          contact_email: contactEmail.trim(),
          contact_phone: contactPhone.trim(),
          contact_telegram: contactTelegram.trim(),
        });
      }
      case "Sources & Links":
        return saveAndNext({
          links: links.filter((l) => l.label.trim() && l.url.trim()),
        });
      case "Visibility":
        return saveAndNext({ visibility });
      default:
        return saveAndNext({});
    }
  }

  function onSkip() {
    setError(null);
    if (last) navigate("/directory", { replace: true });
    else setStep((s) => s + 1);
  }

  return (
    <div className="flex h-full flex-col bg-background">
      <header className="shrink-0 px-5 pt-6">
        <div className="mx-auto w-full max-w-lg">
          <p className="font-mono text-[10px] uppercase tracking-[0.18em] text-faint">
            Edge Mosaic
          </p>
          <h1 className="font-display text-2xl font-bold tracking-tight">
            Set up your profile
          </h1>
          <p className="mt-1 font-mono text-xs text-muted-foreground">
            Step {step + 1} of {STEPS.length} — {STEPS[step]}
          </p>
          <div className="mt-3 flex gap-1.5" aria-hidden>
            {STEPS.map((s, i) => (
              <span
                key={s}
                className={cn(
                  "h-1 flex-1 rounded-full",
                  i <= step ? "bg-marigold" : "bg-border"
                )}
              />
            ))}
          </div>
        </div>
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto px-5 py-6">
        <div className="mx-auto flex w-full max-w-lg flex-col gap-5">
          {STEPS[step] === "Name" && (
            <>
              <Field
                label="Display name"
                hint="Shown on your digests and in the Directory."
                error={nameTouched ? nameError ?? undefined : undefined}
              >
                <Input
                  autoFocus
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="Jane S."
                  className={cn(nameTouched && nameError && "border-destructive")}
                />
              </Field>
              <Field label="Username">
                <Input
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  placeholder="janes"
                  autoCapitalize="none"
                  autoCorrect="off"
                  spellCheck={false}
                />
                <UsernameHint username={username} status={usernameStatus} />
              </Field>
            </>
          )}

          {STEPS[step] === "About you" && (
            <>
              <div className="flex flex-wrap gap-6">
                <ImageUploader
                  kind="tile"
                  label="Mosaic tile"
                  url={user?.tile_image_url ?? null}
                  onUser={applyUser}
                />
                <ImageUploader
                  kind="profile"
                  label="Profile photo"
                  url={user?.profile_image_url ?? null}
                  onUser={applyUser}
                />
              </div>
              <p className="-mt-2 text-xs text-muted-foreground">
                Your tile is your square in the Directory mosaic. Skip it and we'll generate
                one from your name.
              </p>
              <BioField value={bio} onChange={setBio} />
              <CitiesEditor cities={cities} onChange={setCities} />
              <ContactFields
                email={contactEmail}
                phone={contactPhone}
                telegram={contactTelegram}
                onEmail={setContactEmail}
                onPhone={setContactPhone}
                onTelegram={setContactTelegram}
              />
            </>
          )}

          {STEPS[step] === "Sources & Links" && (
            <>
              <div className="flex flex-col gap-3">
                <div>
                  <h3 className="font-display text-base font-semibold">Feed sources</h3>
                  <p className="text-sm text-muted-foreground">
                    Add the links to where you publish content — RSS, Substack, Bluesky,
                    Mastodon, X, etc. New content will show up in your subscribers' digests.
                  </p>
                </div>
                <SourcesEditor onVerifying={setSourcesVerifying} hideHint />
              </div>
              <hr className="border-border" />
              <div className="flex flex-col gap-3">
                <div>
                  <h3 className="font-display text-base font-semibold">Links</h3>
                  <p className="text-sm text-muted-foreground">
                    Add other links — personal site, company site, other socials, etc. These
                    won't show up in digests.
                  </p>
                </div>
                <LinksEditor links={links} onChange={setLinks} hideLabel />
              </div>
            </>
          )}

          {STEPS[step] === "Visibility" && (
            <VisibilityToggle value={visibility} onChange={setVisibility} />
          )}

          {error && <p className="text-sm text-destructive">{error}</p>}
        </div>
      </div>

      <footer
        className="shrink-0 border-t border-border bg-card px-5 py-3"
        style={{ paddingBottom: "calc(0.75rem + env(safe-area-inset-bottom))" }}
      >
        <div className="mx-auto flex w-full max-w-lg items-center justify-between gap-3">
          <Button
            type="button"
            variant="ghost"
            disabled={step === 0 || updateMe.isPending}
            onClick={() => {
              setError(null);
              setStep((s) => s - 1);
            }}
          >
            Back
          </Button>
          <div className="flex items-center gap-2">
            {/* Name is required; every other step can be skipped for now. */}
            {step > 0 && (
              <Button type="button" variant="ghost" disabled={sourcesBlocked} onClick={onSkip}>
                Skip
              </Button>
            )}
            <Button type="button" disabled={continueDisabled} onClick={onNext}>
              {updateMe.isPending ? "Saving…" : last ? "Finish" : "Continue"}
            </Button>
          </div>
        </div>
      </footer>
    </div>
  );
}

type UsernameStatus = "idle" | "checking" | "ok" | "taken" | "invalid";

// Debounced live availability check for the chosen handle. The backend treats the user's
// own current username as available, so re-saving the seeded value won't read as "taken".
function useUsernameAvailability(username: string): UsernameStatus {
  const [status, setStatus] = useState<UsernameStatus>("idle");
  useEffect(() => {
    const handle = username.trim().toLowerCase();
    if (!handle) {
      setStatus("idle");
      return;
    }
    setStatus("checking");
    const id = setTimeout(async () => {
      try {
        const r = await api.checkUsername(handle);
        setStatus(!r.valid ? "invalid" : r.available ? "ok" : "taken");
      } catch {
        setStatus("idle"); // network hiccup → let the server validate on submit
      }
    }, 400);
    return () => clearTimeout(id);
  }, [username]);
  return status;
}

function UsernameHint({
  username,
  status,
}: {
  username: string;
  status: UsernameStatus;
}) {
  const handle = username.trim().toLowerCase();
  if (status === "ok")
    return (
      <span className="text-xs text-[#1c7c3c]">
        edge-mosaic.com/p/{handle} is available
      </span>
    );
  if (status === "taken")
    return <span className="text-xs text-destructive">That username is already taken.</span>;
  if (status === "invalid")
    return (
      <span className="text-xs text-destructive">
        3–30 characters: letters, numbers, - or _.
      </span>
    );
  if (status === "checking")
    return <span className="text-xs text-muted-foreground">Checking…</span>;
  return (
    <span className="text-xs text-muted-foreground">
      Your profile lives at edge-mosaic.com/p/your-handle.
    </span>
  );
}
