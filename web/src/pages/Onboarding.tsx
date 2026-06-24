import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, ApiError, type Link, type MePatch, type Visibility } from "../api";
import { useAuth } from "../auth";
import { useSources, useUpdateMe } from "../hooks/queries";
import {
  BioField,
  CitiesEditor,
  ContactFields,
  isValidEmail,
  isValidPhone,
  isValidTelegram,
  LinksEditor,
  VisibilityToggle,
} from "../components/ProfileFields";
import { SourcesEditor } from "../components/SourcesEditor";
import { trackOnboardingStep } from "../sentry";

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
        const trimmed = name.trim();
        const handle = username.trim().toLowerCase();
        if (!trimmed) {
          setError("Please enter a display name.");
          return;
        }
        if (!handle) {
          setError("Please choose a username.");
          return;
        }
        if (usernameStatus === "invalid") {
          setError("Usernames are 3–30 characters: letters, numbers, - or _.");
          return;
        }
        if (usernameStatus === "taken") {
          setError("That username is already taken.");
          return;
        }
        // A still-"checking" username is re-validated server-side (409/422 surfaces here).
        return saveAndNext({ display_name: trimmed, username: handle });
      }
      case "About you": {
        // Contact fields are optional, but a *filled* one must be structurally valid.
        if (!isValidEmail(contactEmail)) {
          setError("Enter a valid email address (or clear it).");
          return;
        }
        if (!isValidPhone(contactPhone)) {
          setError("Enter a valid phone number (or leave it blank).");
          return;
        }
        if (!isValidTelegram(contactTelegram)) {
          setError("Telegram handle is 5–32 characters: letters, numbers, or underscores.");
          return;
        }
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
    <div className="centered">
      <div className="card wizard stack">
        <div className="wizard-head">
          <h1>Set up your profile</h1>
          <p className="muted small">
            Step {step + 1} of {STEPS.length} — {STEPS[step]}
          </p>
          <div className="wizard-progress" aria-hidden>
            {STEPS.map((s, i) => (
              <span key={s} className={`dot ${i <= step ? "dot-on" : ""}`} />
            ))}
          </div>
        </div>

        <div className="wizard-body stack">
          {STEPS[step] === "Name" && (
            <>
              <label className="field">
                <span>Display name</span>
                <input
                  autoFocus
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="Jane S."
                />
                <span className="muted small">
                  Shown on your digests and in the Directory.
                </span>
              </label>
              <label className="field">
                <span>Username</span>
                <input
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  placeholder="janes"
                  autoCapitalize="none"
                  autoCorrect="off"
                  spellCheck={false}
                />
                <UsernameHint username={username} status={usernameStatus} />
              </label>
            </>
          )}

          {STEPS[step] === "About you" && (
            <>
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
              <div className="stack">
                <div>
                  <h3>Feed sources</h3>
                  <p className="muted small">
                    Add the links to where you publish content — RSS, Substack, Bluesky, Mastodon, X, etc. New content will show up in your followers' digests.
                  </p>
                </div>
                <SourcesEditor onVerifying={setSourcesVerifying} hideHint />
              </div>
              <hr className="section-divider" />
              <div className="stack">
                <div>
                  <h3>Links</h3>
                  <p className="muted small">
                    Add other links — personal site, company site, other socials, etc. These won't show up in digests.
                  </p>
                </div>
                <LinksEditor links={links} onChange={setLinks} hideLabel />
              </div>
            </>
          )}

          {STEPS[step] === "Visibility" && (
            <VisibilityToggle value={visibility} onChange={setVisibility} />
          )}
        </div>

        {error && <p className="error">{error}</p>}

        <div className="wizard-nav">
          <button
            type="button"
            className="btn btn-ghost"
            disabled={step === 0 || updateMe.isPending}
            onClick={() => {
              setError(null);
              setStep((s) => s - 1);
            }}
          >
            Back
          </button>
          <div className="settings-row">
            {/* Name is required; every other step can be skipped for now. */}
            {step > 0 && (
              <button
                type="button"
                className="btn btn-ghost"
                disabled={
                  STEPS[step] === "Sources & Links" &&
                  (sourcesVerifying || (sources.data?.length ?? 0) === 0)
                }
                onClick={onSkip}
              >
                Skip
              </button>
            )}
            <button
              type="button"
              className="btn btn-primary"
              disabled={
                updateMe.isPending ||
                (STEPS[step] === "Sources & Links" &&
                  (sourcesVerifying || (sources.data?.length ?? 0) === 0))
              }
              onClick={onNext}
            >
              {updateMe.isPending ? "Saving…" : last ? "Finish" : "Continue"}
            </button>
          </div>
        </div>
      </div>
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
    return <span className="success small">edge-mosaic.com/p/{handle} is available</span>;
  if (status === "taken")
    return <span className="error small">That username is already taken.</span>;
  if (status === "invalid")
    return (
      <span className="error small">3–30 characters: letters, numbers, - or _.</span>
    );
  if (status === "checking")
    return <span className="muted small">Checking…</span>;
  return (
    <span className="muted small">Your profile lives at edge-mosaic.com/p/your-handle.</span>
  );
}
