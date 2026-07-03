import { useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { ChevronDown, ExternalLink } from "lucide-react";
import { useQueryClient } from "@tanstack/react-query";
import type { DigestFeeder, DigestItem } from "../api";
import { useAuth } from "../auth";
import { Pills } from "./Directory";
import {
  useDigestPreview,
  useSubscriptions,
  useUnsubscribeFeeder,
  useUpdateMe,
} from "../hooks/queries";
import { Button } from "@/components/ui/button";
import { Card, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";

export function Digest() {
  const { user, applyUser } = useAuth();
  const qc = useQueryClient();
  const navigate = useNavigate();
  const location = useLocation();
  const subs = useSubscriptions();
  const preview = useDigestPreview();
  const unsubscribe = useUnsubscribeFeeder();
  const [subsOpen, setSubsOpen] = useState(false);
  // Changing frequency reshapes the trailing preview window → revalidate the preview.
  const updateMe = useUpdateMe((fresh) => {
    applyUser(fresh);
    qc.invalidateQueries({ queryKey: ["digest-preview"] });
  });

  // Open a feeder's profile as an overlay over the Digest (same pattern as the Directory).
  const openProfile = (username: string) =>
    navigate(`/p/${username}`, { state: { backgroundLocation: location } });

  const subCount = subs.data?.length ?? 0;

  return (
    <div className="absolute inset-0 overflow-y-auto">
      <div className="mx-auto flex w-full max-w-2xl flex-col gap-4 px-4 py-5">
        <header>
          <p className="font-mono text-[10px] lg:text-[12px] uppercase tracking-[0.18em] text-faint">
            Edge Mosaic
          </p>
          <h1 className="font-display text-2xl font-bold tracking-tight">Digest</h1>
        </header>

        <Card className="flex flex-col gap-3">
          <CardTitle>Delivery settings</CardTitle>
          <div className="flex flex-wrap items-center gap-5">
            <label className="flex items-center gap-2 text-sm">
              <span className="text-muted-foreground">Frequency</span>
              <select
                className="h-9 rounded-md border border-input bg-card px-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                value={user?.digest_frequency ?? "weekly"}
                disabled={updateMe.isPending}
                onChange={(e) =>
                  updateMe.mutate({ digest_frequency: e.target.value as "weekly" | "monthly" })
                }
              >
                <option value="weekly">Weekly</option>
                <option value="monthly">Monthly</option>
              </select>
            </label>
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                className="size-4 accent-marigold"
                checked={user?.digest_paused ?? false}
                disabled={updateMe.isPending}
                onChange={(e) => updateMe.mutate({ digest_paused: e.target.checked })}
              />
              <span>Pause digest emails</span>
            </label>
          </div>
        </Card>

        {/* Subscriptions collapse to a single header row so the preview below gets the space.
            The count stays visible while collapsed. */}
        <Card className="flex flex-col gap-3">
          <button
            type="button"
            onClick={() => setSubsOpen((o) => !o)}
            className="flex items-center justify-between gap-2 text-left"
            aria-expanded={subsOpen}
          >
            <CardTitle>
              Subscriptions
              {subCount > 0 && (
                <span className="ml-1.5 font-normal text-muted-foreground">{subCount}</span>
              )}
            </CardTitle>
            <ChevronDown
              className={cn(
                "size-4 shrink-0 text-muted-foreground transition-transform",
                subsOpen && "rotate-180"
              )}
            />
          </button>
          {subsOpen &&
            (subs.isLoading ? (
              <p className="text-muted-foreground">Loading…</p>
            ) : subCount === 0 ? (
              <p className="text-muted-foreground">
                You're not subscribed to anyone yet. Find people in the Directory.
              </p>
            ) : (
              <ul className="flex flex-col divide-y divide-border">
                {subs.data?.map((s) => (
                  <li className="flex items-start gap-3 py-3 first:pt-0 last:pb-0" key={s.feeder_id}>
                    <div className="flex min-w-0 flex-1 flex-col gap-1.5">
                      <button
                        type="button"
                        onClick={() => openProfile(s.username)}
                        className="w-fit text-left font-semibold transition-colors hover:text-marigold"
                      >
                        {s.display_name ?? "Unnamed"}
                      </button>
                      <Pills platforms={s.platforms} links={[]} />
                    </div>
                    <Button
                      variant="ghost"
                      size="sm"
                      disabled={unsubscribe.isPending}
                      onClick={() => unsubscribe.mutate(s.feeder_id)}
                    >
                      Unsubscribe
                    </Button>
                  </li>
                ))}
              </ul>
            ))}
        </Card>

        <Card className="flex flex-col gap-4">
          <div className="flex flex-col gap-1">
            <CardTitle>Preview</CardTitle>
            <p className="text-sm text-muted-foreground">
              A representative sample of what your next digest will look like.
            </p>
          </div>
          {preview.isLoading ? (
            <p className="text-muted-foreground">Loading preview…</p>
          ) : preview.isError ? (
            <p className="text-destructive">Couldn't load the preview.</p>
          ) : !preview.data ? null : preview.data.feeders.length === 0 &&
            preview.data.quiet_feeders.length === 0 ? (
            <p className="text-muted-foreground">
              Nothing to preview yet — follow some people with recent posts.
            </p>
          ) : (
            <div className="flex flex-col gap-6">
              {/* Mirrors the email: compact (one line per feeder) once many are active,
                  else the spacious group-by-source layout. */}
              {preview.data.compact ? (
                <ul className="flex flex-col divide-y divide-border">
                  {preview.data.feeders.map((f) => (
                    <CompactRow key={f.feeder_id} feeder={f} />
                  ))}
                </ul>
              ) : (
                <div className="flex flex-col gap-6">
                  {preview.data.feeders.map((f) => (
                    <FeederBlock key={f.feeder_id} feeder={f} />
                  ))}
                </div>
              )}
              {preview.data.quiet_feeders.length > 0 && (
                <div className="border-t border-border pt-4">
                  <p className="font-mono text-[10px] uppercase tracking-[0.14em] text-faint">
                    No updates
                  </p>
                  <p className="mt-1 text-sm text-muted-foreground">
                    Nothing this period from {preview.data.quiet_feeders.join(", ")}.
                  </p>
                </div>
              )}
            </div>
          )}
        </Card>
      </div>
    </div>
  );
}

// Mirrors the email layout: feeder → per-source blocks (long-form sources first). All
// scraped strings render as text (React escapes by default) — NEVER
// dangerouslySetInnerHTML on feed/Bluesky content (XSS rule, §2).
function FeederBlock({ feeder }: { feeder: DigestFeeder }) {
  return (
    <section className="border-t border-border pt-4 first:border-t-0 first:pt-0">
      <h3 className="text-sm text-muted-foreground">
        From <span className="font-semibold text-foreground">{feeder.display_name ?? "Unnamed"}</span>
      </h3>
      <div className="mt-3 flex flex-col gap-4">
        {feeder.sources.map((source, si) => (
          <div className="border-l-2 border-border pl-3" key={`src-${si}`}>
            <p className="mb-1.5 font-mono text-[10px] uppercase tracking-[0.14em] text-faint">
              {source.label}
            </p>
            <div className="flex flex-col gap-2.5">
              {source.longs.map((item, i) => (
                <LongItem key={`l-${i}`} item={item} />
              ))}
              {source.shorts.length > 0 && (
                <ul className="flex flex-col gap-1.5">
                  {source.shorts.map((item, i) => (
                    <li key={`s-${i}`}>
                      <OutLink url={item.url} className="text-sm">
                        {shortText(item)}
                      </OutLink>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}

// Compact format: one line per feeder, showing its single representative item.
function CompactRow({ feeder }: { feeder: DigestFeeder }) {
  const item = feeder.selected;
  const label = item.title ?? item.text ?? item.excerpt ?? item.url;
  return (
    <li className="flex flex-col gap-0.5 py-2.5 first:pt-0 last:pb-0 sm:flex-row sm:items-baseline sm:gap-2">
      <span className="shrink-0 text-sm font-semibold">{feeder.display_name ?? "Unnamed"}</span>
      <OutLink url={item.url} className="min-w-0 max-w-full text-sm text-muted-foreground">
        <span className="min-w-0 truncate">
          {label.length > 100 ? `${label.slice(0, 100)}…` : label}
        </span>
      </OutLink>
    </li>
  );
}

function LongItem({ item }: { item: DigestItem }) {
  return (
    <div>
      <OutLink url={item.url} className="font-semibold">
        {item.title ?? item.url}
      </OutLink>
      {item.excerpt && (
        <p className="mt-0.5 text-sm leading-relaxed text-muted-foreground">{item.excerpt}</p>
      )}
    </div>
  );
}

// A single outbound link with a trailing arrow so it's unmistakably a link off-site.
function OutLink({
  url,
  className,
  children,
}: {
  url: string;
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <a
      href={url}
      target="_blank"
      rel="noreferrer noopener"
      className={cn(
        "group inline-flex items-baseline gap-1 text-foreground transition-colors hover:text-marigold",
        className
      )}
    >
      {children}
      <ExternalLink className="size-3 shrink-0 translate-y-0.5 text-faint transition-colors group-hover:text-marigold" />
    </a>
  );
}

function shortText(item: DigestItem): string {
  const body = item.text ?? item.title ?? item.url;
  return body.length > 100 ? `${body.slice(0, 100)}…` : body;
}
