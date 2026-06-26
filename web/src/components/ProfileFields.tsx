// Reusable, controlled profile-field components shared by the onboarding wizard and the
// Profile page. They're presentational (value + onChange) except ImageUploader, which owns
// the upload/delete mutation since images persist immediately (they're files, not JSON).
import { useRef, useState } from "react";
import { X } from "lucide-react";
import { ApiError, type ImageKind, type Link, type User, type Visibility } from "../api";
import { useDeleteImage, useUploadImage } from "../hooks/queries";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";

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

// --- contact-field validation (all optional → empty is always valid; we only check the
// structure of a *filled* value). The backend stores these as free text, so this is a UX
// guard, not a security boundary. ---------------------------------------------------------
const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
// Lenient phone check: at least 7 digits, allowing +, spaces, -, (), . separators.
const PHONE_RE = /^\+?[\d\s().-]{7,}$/;
// Telegram handle: optional leading '@', then 5–32 of [A-Za-z0-9_].
const TELEGRAM_RE = /^@?[A-Za-z0-9_]{5,32}$/;

export const isValidEmail = (v: string) => v.trim() === "" || EMAIL_RE.test(v.trim());
export const isValidPhone = (v: string) =>
  v.trim() === "" || (PHONE_RE.test(v.trim()) && (v.match(/\d/g)?.length ?? 0) >= 7);
export const isValidTelegram = (v: string) => v.trim() === "" || TELEGRAM_RE.test(v.trim());

// Small labelled-field wrapper for consistent spacing/typography.
export function Field({
  label,
  hint,
  error,
  htmlFor,
  children,
}: {
  label?: string;
  hint?: string;
  error?: string;
  htmlFor?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex flex-col gap-1.5">
      {label && <Label htmlFor={htmlFor}>{label}</Label>}
      {children}
      {error ? (
        <span className="text-xs text-destructive">{error}</span>
      ) : hint ? (
        <span className="text-xs text-muted-foreground">{hint}</span>
      ) : null}
    </div>
  );
}

export function BioField({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  return (
    <Field label="Bio" hint={`${value.length}/${BIO_MAX_CHARS}`}>
      <Textarea
        rows={3}
        maxLength={BIO_MAX_CHARS}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder="A sentence or two about you."
      />
    </Field>
  );
}

export function ContactFields({
  email,
  phone,
  telegram,
  onEmail,
  onPhone,
  onTelegram,
}: {
  email: string;
  phone: string;
  telegram: string;
  onEmail: (v: string) => void;
  onPhone: (v: string) => void;
  onTelegram: (v: string) => void;
}) {
  // Inline structure check, shown only once a field has a (non-empty) value to validate.
  const emailBad = email.trim() !== "" && !isValidEmail(email);
  const phoneBad = phone.trim() !== "" && !isValidPhone(phone);
  const telegramBad = telegram.trim() !== "" && !isValidTelegram(telegram);
  return (
    <div className="flex flex-col gap-4">
      <Field label="Public contact email" error={emailBad ? "Enter a valid email address." : undefined}>
        {/* Pre-filled with your sign-in email; clear it with the ✕ if you'd rather not show it. */}
        <div className="relative">
          <Input
            type="email"
            value={email}
            onChange={(e) => onEmail(e.target.value)}
            placeholder="you@example.com"
            aria-invalid={emailBad}
            className={cn(email !== "" && "pr-9", emailBad && "border-destructive")}
          />
          {email !== "" && (
            <button
              type="button"
              aria-label="Clear email"
              onClick={() => onEmail("")}
              className="absolute right-2 top-1/2 -translate-y-1/2 rounded p-1 text-muted-foreground hover:text-foreground"
            >
              <X className="size-4" />
            </button>
          )}
        </div>
      </Field>
      <Field label="Phone" error={phoneBad ? "Enter a valid phone number." : undefined}>
        <Input
          type="tel"
          value={phone}
          onChange={(e) => onPhone(e.target.value)}
          placeholder="optional"
          aria-invalid={phoneBad}
          className={cn(phoneBad && "border-destructive")}
        />
      </Field>
      <Field
        label="Telegram"
        hint="Your @username on Telegram."
        error={
          telegramBad
            ? "Handle is 5–32 characters: letters, numbers, or underscores."
            : undefined
        }
      >
        <Input
          value={telegram}
          onChange={(e) => onTelegram(e.target.value)}
          placeholder="@handle (optional)"
          autoCapitalize="none"
          autoCorrect="off"
          spellCheck={false}
          aria-invalid={telegramBad}
          className={cn(telegramBad && "border-destructive")}
        />
      </Field>
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
    <Field label="City / cities">
      <div className="flex flex-col gap-2">
        {cities.map((city, i) => (
          <div className="flex items-center gap-2" key={i}>
            <Input value={city} onChange={(e) => set(i, e.target.value)} placeholder="City" />
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={() => onChange(cities.filter((_, idx) => idx !== i))}
            >
              Remove
            </Button>
          </div>
        ))}
        {cities.length < MAX_CITIES && (
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="self-start"
            onClick={() => onChange([...cities, ""])}
          >
            + Add city
          </Button>
        )}
      </div>
    </Field>
  );
}

export function LinksEditor({
  links,
  onChange,
  hideLabel = false,
}: {
  links: Link[];
  onChange: (next: Link[]) => void;
  hideLabel?: boolean;
}) {
  function set(i: number, patch: Partial<Link>) {
    onChange(links.map((l, idx) => (idx === i ? { ...l, ...patch } : l)));
  }
  return (
    <Field
      label={hideLabel ? undefined : "Other links"}
      hint={hideLabel ? undefined : "Personal site, portfolio, socials — not feed sources."}
    >
      <div className="flex flex-col gap-2">
        {links.map((link, i) => (
          <div key={i} className="flex flex-col gap-1 rounded-lg border border-border p-2.5">
            <Input
              value={link.label}
              onChange={(e) => set(i, { label: e.target.value })}
              placeholder="Label (e.g. Website)"
            />
            <div className="flex items-center gap-1.5">
              <Input
                className="flex-1"
                value={link.url}
                onChange={(e) => set(i, { url: e.target.value })}
                onBlur={(e) => set(i, { url: normalizeLinkUrl(e.target.value) })}
                placeholder="https://…"
              />
              <Button
                type="button"
                variant="ghost"
                size="icon"
                className="shrink-0"
                onClick={() => onChange(links.filter((_, idx) => idx !== i))}
              >
                <X className="size-4" />
              </Button>
            </div>
          </div>
        ))}
        {links.length < MAX_LINKS && (
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="self-start"
            onClick={() => onChange([...links, { label: "", url: "" }])}
          >
            + Add link
          </Button>
        )}
      </div>
    </Field>
  );
}

export function VisibilityToggle({
  value,
  onChange,
}: {
  value: Visibility;
  onChange: (v: Visibility) => void;
}) {
  const options: { v: Visibility; title: string; desc: string }[] = [
    {
      v: "community",
      title: "Entire edge community",
      desc: "Anyone in the community can find you.",
    },
    {
      v: "village",
      title: "Just my village(s)",
      desc: "Only people who share a village with you.",
    },
  ];
  return (
    <fieldset className="flex flex-col gap-2">
      <legend className="mb-1 text-sm font-medium">Who can find you in the Directory?</legend>
      {options.map((o) => {
        const active = value === o.v;
        return (
          <label
            key={o.v}
            className={cn(
              "flex cursor-pointer flex-col rounded-xl border p-3 transition-colors",
              active ? "border-marigold bg-secondary" : "border-border hover:bg-secondary/60"
            )}
          >
            <input
              type="radio"
              name="visibility"
              className="sr-only"
              checked={active}
              onChange={() => onChange(o.v)}
            />
            <span className="block font-medium">{o.title}</span>
            <span className="block text-sm text-muted-foreground">{o.desc}</span>
          </label>
        );
      })}
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

  // One photo, framed as a square — it doubles as your square in the Directory mosaic.
  const previewShape = "size-20 rounded-lg";

  return (
    <div className="flex flex-col gap-1.5">
      <Label>{label}</Label>
      <div className="flex items-center gap-4">
        {url ? (
          <img
            className={cn("border border-border object-cover", previewShape)}
            src={url}
            alt={label}
          />
        ) : (
          <div
            className={cn(
              "flex items-center justify-center border border-border bg-secondary text-xl text-muted-foreground",
              previewShape
            )}
            aria-hidden
          >
            🙂
          </div>
        )}
        <div className="flex flex-col items-start gap-1">
          <input
            ref={inputRef}
            type="file"
            accept="image/png,image/jpeg,image/webp"
            hidden
            onChange={onPick}
          />
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={busy}
            onClick={() => inputRef.current?.click()}
          >
            {busy ? "Working…" : url ? "Replace" : "Upload"}
          </Button>
          {url && (
            <Button
              type="button"
              variant="ghost"
              size="sm"
              disabled={busy}
              onClick={() => remove.mutate(kind)}
            >
              Remove
            </Button>
          )}
        </div>
      </div>
      {error && <p className="text-xs text-destructive">{error}</p>}
    </div>
  );
}
