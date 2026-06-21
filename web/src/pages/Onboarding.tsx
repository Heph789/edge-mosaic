import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { ApiError, type Link, type MePatch, type Visibility } from "../api";
import { useAuth } from "../auth";
import { useUpdateMe } from "../hooks/queries";
import {
  BioField,
  CitiesEditor,
  ContactFields,
  ImageUploader,
  LinksEditor,
  VisibilityToggle,
} from "../components/ProfileFields";
import { SourcesEditor } from "../components/SourcesEditor";

// Multi-step onboarding wizard. Step 1 (display name) flips `onboarded` via PATCH /me;
// /onboarding lives outside the RequireOnboarded guard, so later enrichment steps don't
// bounce the user. Every step is skippable except the name. Finish → the app.
const STEPS = ["Name", "About you", "Photos", "Links", "Sources", "Visibility"] as const;

export function Onboarding() {
  const { user, applyUser } = useAuth();
  const navigate = useNavigate();
  const [step, setStep] = useState(0);
  const [error, setError] = useState<string | null>(null);

  // Local form state for the text/list fields, seeded from the current user.
  const [name, setName] = useState(user?.display_name ?? "");
  const [bio, setBio] = useState(user?.bio ?? "");
  const [cities, setCities] = useState<string[]>(user?.cities ?? []);
  const [contactEmail, setContactEmail] = useState(user?.contact_email ?? "");
  const [contactPhone, setContactPhone] = useState(user?.contact_phone ?? "");
  const [links, setLinks] = useState<Link[]>(user?.links ?? []);
  const [visibility, setVisibility] = useState<Visibility>(user?.visibility ?? "community");

  const updateMe = useUpdateMe(applyUser);
  const last = step === STEPS.length - 1;

  // Persist the fields owned by the current step, then advance (or finish).
  async function saveAndNext(patch: MePatch) {
    setError(null);
    try {
      if (Object.keys(patch).length > 0) await updateMe.mutateAsync(patch);
      if (last) navigate("/directory", { replace: true });
      else setStep((s) => s + 1);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't save — try again.");
    }
  }

  function onNext() {
    switch (STEPS[step]) {
      case "Name": {
        const trimmed = name.trim();
        if (!trimmed) {
          setError("Please enter a display name.");
          return;
        }
        return saveAndNext({ display_name: trimmed });
      }
      case "About you":
        return saveAndNext({
          bio: bio.trim(),
          cities: cities.map((c) => c.trim()).filter(Boolean),
          contact_email: contactEmail.trim(),
          contact_phone: contactPhone.trim(),
        });
      case "Links":
        return saveAndNext({
          links: links.filter((l) => l.label.trim() && l.url.trim()),
        });
      case "Visibility":
        return saveAndNext({ visibility });
      // Photos + Sources persist immediately inside their own components.
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
          )}

          {STEPS[step] === "About you" && (
            <>
              <BioField value={bio} onChange={setBio} />
              <CitiesEditor cities={cities} onChange={setCities} />
              <ContactFields
                email={contactEmail}
                phone={contactPhone}
                onEmail={setContactEmail}
                onPhone={setContactPhone}
              />
            </>
          )}

          {STEPS[step] === "Photos" && (
            <>
              <p className="muted small">
                Your profile photo and a tile image for the community mosaic.
              </p>
              <ImageUploader
                kind="profile"
                label="Profile photo"
                url={user?.profile_image_url ?? null}
                onUser={applyUser}
              />
              <ImageUploader
                kind="tile"
                label="Tile image"
                url={user?.tile_image_url ?? null}
                onUser={applyUser}
              />
            </>
          )}

          {STEPS[step] === "Links" && <LinksEditor links={links} onChange={setLinks} />}

          {STEPS[step] === "Sources" && (
            <>
              <p className="muted small">
                Add the feeds you publish — they power your digest and show in the Directory.
              </p>
              <SourcesEditor />
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
              <button type="button" className="btn btn-ghost" onClick={onSkip}>
                Skip
              </button>
            )}
            <button
              type="button"
              className="btn btn-primary"
              disabled={updateMe.isPending}
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
