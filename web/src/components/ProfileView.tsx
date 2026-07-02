// Shared read-only rendering of a public profile, used by the standalone /p/{username}
// page. Kept here (not in Directory) so it has no dependency back on the Directory page.
import type { ProfileSource, PublicProfile } from "../api";
import { UnverifiedBadge } from "./UnverifiedBadge";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { SubscribeButton } from "@/components/SubscribeButton";
import { initialsOf } from "@/lib/mosaic";

export function Avatar60({ url, name, handle }: { url: string | null; name: string | null; handle: string }) {
  return (
    <Avatar className="size-14 border border-border">
      {url && <AvatarImage src={url} alt="" />}
      <AvatarFallback className="text-lg">{initialsOf(name, handle)}</AvatarFallback>
    </Avatar>
  );
}

export function ProfileView({
  profile: p,
  pending,
  onToggleFollow,
}: {
  profile: PublicProfile;
  pending: boolean;
  onToggleFollow: (subscribe: boolean) => void;
}) {
  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-start gap-4">
        <Avatar60 url={p.profile_image_url} name={p.display_name} handle={p.username} />
        <div className="min-w-0 flex-1">
          <h2 className="font-display text-2xl font-semibold tracking-tight">
            {p.display_name ?? "Unnamed"}
          </h2>
          <p className="font-mono text-xs text-muted-foreground">
            @{p.username}
            {p.cities.length > 0 && ` · ${p.cities.join(" · ")}`}
          </p>
        </div>
      </div>

      {p.bio && <p className="text-[15px] leading-relaxed text-foreground/85">{p.bio}</p>}

      <SourceLinks sources={p.sources} />

      {p.links.length > 0 && (
        <Section label="Links">
          <div className="flex flex-wrap gap-1.5">
            {p.links.map((l, i) => (
              <a
                key={i}
                href={l.url}
                target="_blank"
                rel="noreferrer noopener"
                className="rounded-full border border-border px-2.5 py-1 font-mono text-[11px] text-muted-foreground transition-colors hover:border-marigold hover:text-foreground"
              >
                {l.label}
              </a>
            ))}
          </div>
        </Section>
      )}

      {(p.contact_email || p.contact_telegram) && (
        <p className="text-sm text-muted-foreground">
          Contact:{" "}
          {p.contact_email && (
            <a className="text-foreground hover:underline" href={`mailto:${p.contact_email}`}>
              {p.contact_email}
            </a>
          )}
          {p.contact_email && p.contact_telegram && " · "}
          {p.contact_telegram && (
            <a
              className="text-foreground hover:underline"
              href={`https://t.me/${p.contact_telegram}`}
              target="_blank"
              rel="noreferrer noopener"
            >
              @{p.contact_telegram}
            </a>
          )}
        </p>
      )}

      <SubscribeButton
        className="self-start"
        hasFeeders={p.sources.length > 0}
        isSubscribed={p.is_subscribed}
        pending={pending}
        onToggle={onToggleFollow}
        name={p.display_name}
      />
    </div>
  );
}

function Section({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <p className="mb-2 font-mono text-[10px] uppercase tracking-[0.12em] text-faint">
        {label}
      </p>
      {children}
    </div>
  );
}

// The feeder's content feeds, as clickable links (labelled by pulled title, with a
// platform pill). Falls back to a muted note when the feeder has no sources.
function SourceLinks({ sources }: { sources: ProfileSource[] }) {
  if (sources.length === 0)
    return <span className="text-sm text-muted-foreground">no sources yet</span>;
  return (
    <Section label="Feeds">
      <ul className="flex flex-col gap-2">
        {sources.map((s, i) => (
          <li key={i} className="flex min-w-0 items-center gap-2">
            <a
              href={s.url}
              target="_blank"
              rel="noreferrer noopener"
              className="truncate text-sm underline-offset-2 hover:underline"
            >
              {s.title ?? s.url}
            </a>
            <span className="shrink-0 rounded-full border border-border bg-secondary px-2 py-0.5 font-mono text-[10px] text-muted-foreground">
              {s.label}
            </span>
            {s.status === "unverified" && <UnverifiedBadge />}
          </li>
        ))}
      </ul>
    </Section>
  );
}
