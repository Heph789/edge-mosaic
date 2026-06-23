// Reusable, controlled profile-field components shared by the onboarding wizard and the
// Profile page. They're presentational (value + onChange) except ImageUploader, which owns
// the upload/delete mutation since images persist immediately (they're files, not JSON).
import { useRef, useState } from "react";
import { ApiError, type ImageKind, type Link, type User, type Visibility } from "../api";
import { useDeleteImage, useUploadImage } from "../hooks/queries";

// Mirror the caps in api/app/config.py.
export const BIO_MAX_CHARS = 280;
export const MAX_CITIES = 5;
export const MAX_LINKS = 10;

// Mirrors api/app/main.py `_normalize_url`: default a scheme-less link to https:// so
// "chasejeter.com" opens as a real URL instead of a relative path. Leaves
// mailto:/tel:/http(s):// untouched. Applied on blur so the user sees it auto-populate.
const URL_SCHEME_RE = /^[a-z][a-z0-9+.-]*:/i;
export function normalizeLinkUrl(url: string): string {
  const trimmed = url.trim();
  if (trimmed && !URL_SCHEME_RE.test(trimmed)) return `https://${trimmed}`;
  return trimmed;
}

export function BioField({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  return (
    <label className="field">
      <span>Bio</span>
      <textarea
        rows={3}
        maxLength={BIO_MAX_CHARS}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder="A sentence or two about you."
      />
      <span className="muted small">
        {value.length}/{BIO_MAX_CHARS}
      </span>
    </label>
  );
}

export function ContactFields({
  email,
  phone,
  onEmail,
  onPhone,
}: {
  email: string;
  phone: string;
  onEmail: (v: string) => void;
  onPhone: (v: string) => void;
}) {
  return (
    <div className="stack">
      <label className="field">
        <span>Public contact email</span>
        <input
          type="email"
          value={email}
          onChange={(e) => onEmail(e.target.value)}
          placeholder="you@example.com"
        />
      </label>
      <label className="field">
        <span>Phone</span>
        <input
          type="tel"
          value={phone}
          onChange={(e) => onPhone(e.target.value)}
          placeholder="optional"
        />
      </label>
    </div>
  );
}

export function CitiesEditor({
  cities,
  onChange,
}: {
  cities: string[];
  onChange: (next: string[]) => void;
}) {
  function set(i: number, v: string) {
    onChange(cities.map((c, idx) => (idx === i ? v : c)));
  }
  return (
    <div className="field">
      <span>City / cities</span>
      <div className="stack">
        {cities.map((city, i) => (
          <div className="settings-row" key={i}>
            <input
              value={city}
              onChange={(e) => set(i, e.target.value)}
              placeholder="City"
            />
            <button
              type="button"
              className="btn btn-ghost"
              onClick={() => onChange(cities.filter((_, idx) => idx !== i))}
            >
              Remove
            </button>
          </div>
        ))}
        {cities.length < MAX_CITIES && (
          <button type="button" className="btn" onClick={() => onChange([...cities, ""])}>
            + Add city
          </button>
        )}
      </div>
    </div>
  );
}

export function LinksEditor({
  links,
  onChange,
}: {
  links: Link[];
  onChange: (next: Link[]) => void;
}) {
  function set(i: number, patch: Partial<Link>) {
    onChange(links.map((l, idx) => (idx === i ? { ...l, ...patch } : l)));
  }
  return (
    <div className="field">
      <span>Links</span>
      <p className="muted small">Personal site, portfolio, socials — not feed sources.</p>
      <div className="stack">
        {links.map((link, i) => (
          <div className="link-row" key={i}>
            <input
              className="link-label"
              value={link.label}
              onChange={(e) => set(i, { label: e.target.value })}
              placeholder="Label"
            />
            <input
              className="link-url"
              value={link.url}
              onChange={(e) => set(i, { url: e.target.value })}
              onBlur={(e) => set(i, { url: normalizeLinkUrl(e.target.value) })}
              placeholder="https://…"
            />
            <button
              type="button"
              className="btn btn-ghost"
              onClick={() => onChange(links.filter((_, idx) => idx !== i))}
            >
              Remove
            </button>
          </div>
        ))}
        {links.length < MAX_LINKS && (
          <button
            type="button"
            className="btn"
            onClick={() => onChange([...links, { label: "", url: "" }])}
          >
            + Add link
          </button>
        )}
      </div>
    </div>
  );
}

export function VisibilityToggle({
  value,
  onChange,
}: {
  value: Visibility;
  onChange: (v: Visibility) => void;
}) {
  return (
    <fieldset className="field visibility-toggle">
      <legend>Who can find you in the Directory?</legend>
      <label className="radio-row">
        <input
          type="radio"
          name="visibility"
          checked={value === "community"}
          onChange={() => onChange("community")}
        />
        <span>
          <strong>Entire edge community</strong>
          <span className="muted small"> — anyone in the community can find you</span>
        </span>
      </label>
      <label className="radio-row">
        <input
          type="radio"
          name="visibility"
          checked={value === "village"}
          onChange={() => onChange("village")}
        />
        <span>
          <strong>Just my village(s)</strong>
          <span className="muted small"> — only people who share a village with you</span>
        </span>
      </label>
    </fieldset>
  );
}

export function ImageUploader({
  kind,
  label,
  url,
  onUser,
}: {
  kind: ImageKind;
  label: string;
  url: string | null;
  onUser: (u: User) => void;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [error, setError] = useState<string | null>(null);
  const upload = useUploadImage(onUser);
  const remove = useDeleteImage(onUser);
  const busy = upload.isPending || remove.isPending;

  async function onPick(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    e.target.value = ""; // allow re-picking the same file
    if (!file) return;
    setError(null);
    try {
      await upload.mutateAsync({ kind, file });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Upload failed — try again.");
    }
  }

  return (
    <div className={`image-uploader image-uploader--${kind}`}>
      <span className="field-label">{label}</span>
      <div className="image-uploader-row">
        {url ? (
          <img className={`image-preview image-preview--${kind}`} src={url} alt={label} />
        ) : (
          <div className={`image-placeholder image-preview--${kind}`} aria-hidden>
            {kind === "profile" ? "🙂" : "▦"}
          </div>
        )}
        <div className="stack">
          <input
            ref={inputRef}
            type="file"
            accept="image/png,image/jpeg,image/webp"
            hidden
            onChange={onPick}
          />
          <button
            type="button"
            className="btn"
            disabled={busy}
            onClick={() => inputRef.current?.click()}
          >
            {busy ? "Working…" : url ? "Replace" : "Upload"}
          </button>
          {url && (
            <button
              type="button"
              className="btn btn-ghost"
              disabled={busy}
              onClick={() => remove.mutate(kind)}
            >
              Remove
            </button>
          )}
        </div>
      </div>
      {error && <p className="error small">{error}</p>}
    </div>
  );
}
