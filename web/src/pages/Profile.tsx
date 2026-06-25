import { useEffect, useRef, useState, type FormEvent } from "react";
import { Link as RouterLink, useLocation, useNavigate } from "react-router-dom";
import { ApiError, type Link, type Visibility } from "../api";
import { useAuth } from "../auth";
import { useUpdateMe } from "../hooks/queries";
import {
  BioField,
  CitiesEditor,
  ContactFields,
  ImageUploader,
  isValidEmail,
  isValidPhone,
  isValidTelegram,
  LinksEditor,
  VisibilityToggle,
} from "../components/ProfileFields";
import { SourcesEditor } from "../components/SourcesEditor";
import { Button } from "@/components/ui/button";
import { Card, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";

export function Profile() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();

  async function handleLogout() {
    await logout();
    navigate("/login", { replace: true });
  }

  return (
    <div className="absolute inset-0 overflow-y-auto">
      <div className="mx-auto flex w-full max-w-2xl flex-col gap-4 px-4 py-5">
        <header className="flex items-start justify-between">
          <div>
            <p className="font-mono text-[10px] uppercase tracking-[0.18em] text-faint">
              Edge Mosaic
            </p>
            <h1 className="font-display text-2xl font-bold tracking-tight">Profile</h1>
          </div>
          <Button variant="ghost" size="sm" onClick={handleLogout}>
            Log out
          </Button>
        </header>

        <div className="flex flex-col gap-0.5 text-sm text-muted-foreground">
          <span>{user?.email}</span>
          {user && (
            <span>
              Public profile:{" "}
              <RouterLink
                to={`/p/${user.username}`}
                className="text-foreground underline-offset-2 hover:underline"
              >
                edge-mosaic.com/p/{user.username}
              </RouterLink>
            </span>
          )}
          {user && user.villages.length > 0 && (
            <span>Village: {user.villages.join(", ")}</span>
          )}
        </div>

        <DisplayNameSection />
        <PhotosSection />
        <AboutSection />
      </div>
    </div>
  );
}

function DisplayNameSection() {
  const { user, applyUser } = useAuth();
  const [name, setName] = useState(user?.display_name ?? "");
  const [status, setStatus] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const updateMe = useUpdateMe((fresh) => {
    applyUser(fresh);
    setStatus("Saved.");
  });

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setStatus(null);
    setError(null);
    const trimmed = name.trim();
    if (!trimmed) {
      setError("Display name can't be empty.");
      return;
    }
    try {
      await updateMe.mutateAsync({ display_name: trimmed });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't save — try again.");
    }
  }

  return (
    <Card className="flex flex-col gap-3">
      <CardTitle>Display name</CardTitle>
      <form onSubmit={onSubmit} className="flex items-center gap-2">
        <Input
          value={name}
          onChange={(e) => {
            setName(e.target.value);
            setStatus(null);
          }}
        />
        <Button type="submit" disabled={updateMe.isPending} className="shrink-0">
          {updateMe.isPending ? "Saving…" : "Save"}
        </Button>
      </form>
      {status && <p className="text-xs text-[#1c7c3c]">{status}</p>}
      {error && <p className="text-xs text-destructive">{error}</p>}
    </Card>
  );
}

// Profile photo — one image, shown circular as an avatar and square as the Directory
// mosaic tile. Carries id="photo" so the Directory's "Add photo" control can deep-link
// straight to it (/profile#photo).
function PhotosSection() {
  const { user, applyUser } = useAuth();
  const { hash } = useLocation();
  const photoRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (hash === "#photo") photoRef.current?.scrollIntoView({ behavior: "smooth", block: "center" });
  }, [hash]);

  return (
    <Card className="flex flex-col gap-4" id="photo">
      <CardTitle>Photo</CardTitle>
      <div ref={photoRef}>
        <ImageUploader
          kind="profile"
          label="Profile photo"
          url={user?.profile_image_url ?? null}
          onUser={applyUser}
        />
      </div>
      <p className="text-xs text-muted-foreground">
        This is your square in the Directory mosaic too. Without one, your initials stand in.
      </p>
    </Card>
  );
}

// Bio, cities, contact, links, and visibility — one form, one Save (a single PATCH /me).
function AboutSection() {
  const { user, applyUser } = useAuth();
  const [bio, setBio] = useState(user?.bio ?? "");
  const [cities, setCities] = useState<string[]>(user?.cities ?? []);
  // Pre-fill the public contact email with the sign-in email; the field has a clear button.
  const [contactEmail, setContactEmail] = useState(user?.contact_email ?? user?.email ?? "");
  const [contactPhone, setContactPhone] = useState(user?.contact_phone ?? "");
  const [contactTelegram, setContactTelegram] = useState(user?.contact_telegram ?? "");
  const [links, setLinks] = useState<Link[]>(user?.links ?? []);
  const [visibility, setVisibility] = useState<Visibility>(user?.visibility ?? "community");
  const [status, setStatus] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const updateMe = useUpdateMe((fresh) => {
    applyUser(fresh);
    setStatus("Saved.");
  });

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setStatus(null);
    setError(null);
    // Contact fields are optional, but a filled one must be structurally valid.
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
    try {
      await updateMe.mutateAsync({
        bio: bio.trim(),
        cities: cities.map((c) => c.trim()).filter(Boolean),
        contact_email: contactEmail.trim(),
        contact_phone: contactPhone.trim(),
        contact_telegram: contactTelegram.trim(),
        links: links.filter((l) => l.label.trim() && l.url.trim()),
        visibility,
      });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't save — try again.");
    }
  }

  return (
    <Card className="flex flex-col gap-4">
      <CardTitle>About</CardTitle>
      <form onSubmit={onSubmit} className="flex flex-col gap-5">
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
        <div className="flex flex-col gap-1.5">
          <span className="text-sm font-medium">Sources</span>
          <SourcesEditor hideHint />
        </div>
        <LinksEditor links={links} onChange={setLinks} />
        <VisibilityToggle value={visibility} onChange={setVisibility} />
        <div>
          <Button type="submit" disabled={updateMe.isPending}>
            {updateMe.isPending ? "Saving…" : "Save"}
          </Button>
        </div>
        {status && <p className="text-xs text-[#1c7c3c]">{status}</p>}
        {error && <p className="text-xs text-destructive">{error}</p>}
      </form>
    </Card>
  );
}

