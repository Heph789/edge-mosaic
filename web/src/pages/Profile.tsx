import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { ApiError, type Link, type Visibility } from "../api";
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

export function Profile() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();

  async function handleLogout() {
    await logout();
    navigate("/login", { replace: true });
  }

  return (
    <div className="page stack">
      <div className="page-head">
        <h1>Profile</h1>
        <button className="btn btn-ghost" onClick={handleLogout}>
          Log out
        </button>
      </div>
      <p className="muted small">{user?.email}</p>
      {user && user.villages.length > 0 && (
        <p className="muted small">Village: {user.villages.join(", ")}</p>
      )}

      <DisplayNameSection />
      <PhotosSection />
      <AboutSection />
      <SourcesSection />
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
    <section className="card stack">
      <h2>Display name</h2>
      <form onSubmit={onSubmit} className="settings-row">
        <input
          value={name}
          onChange={(e) => {
            setName(e.target.value);
            setStatus(null);
          }}
        />
        <button className="btn btn-primary" type="submit" disabled={updateMe.isPending}>
          {updateMe.isPending ? "Saving…" : "Save"}
        </button>
      </form>
      {status && <p className="success small">{status}</p>}
      {error && <p className="error small">{error}</p>}
    </section>
  );
}

function PhotosSection() {
  const { user, applyUser } = useAuth();
  return (
    <section className="card stack">
      <h2>Photos</h2>
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
    </section>
  );
}

// Bio, cities, contact, links, and visibility — one form, one Save (a single PATCH /me).
function AboutSection() {
  const { user, applyUser } = useAuth();
  const [bio, setBio] = useState(user?.bio ?? "");
  const [cities, setCities] = useState<string[]>(user?.cities ?? []);
  const [contactEmail, setContactEmail] = useState(user?.contact_email ?? "");
  const [contactPhone, setContactPhone] = useState(user?.contact_phone ?? "");
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
    try {
      await updateMe.mutateAsync({
        bio: bio.trim(),
        cities: cities.map((c) => c.trim()).filter(Boolean),
        contact_email: contactEmail.trim(),
        contact_phone: contactPhone.trim(),
        links: links.filter((l) => l.label.trim() && l.url.trim()),
        visibility,
      });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't save — try again.");
    }
  }

  return (
    <section className="card stack">
      <h2>About</h2>
      <form onSubmit={onSubmit} className="stack">
        <BioField value={bio} onChange={setBio} />
        <CitiesEditor cities={cities} onChange={setCities} />
        <ContactFields
          email={contactEmail}
          phone={contactPhone}
          onEmail={setContactEmail}
          onPhone={setContactPhone}
        />
        <LinksEditor links={links} onChange={setLinks} />
        <VisibilityToggle value={visibility} onChange={setVisibility} />
        <div className="settings-row">
          <button className="btn btn-primary" type="submit" disabled={updateMe.isPending}>
            {updateMe.isPending ? "Saving…" : "Save"}
          </button>
        </div>
        {status && <p className="success small">{status}</p>}
        {error && <p className="error small">{error}</p>}
      </form>
    </section>
  );
}

function SourcesSection() {
  return (
    <section className="card stack">
      <h2>Your sources</h2>
      <SourcesEditor />
    </section>
  );
}
