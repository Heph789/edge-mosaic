import { useQueryClient } from "@tanstack/react-query";
import type { DigestFeeder, DigestItem } from "../api";
import { useAuth } from "../auth";
import { Platforms } from "./Directory";
import {
  useDigestPreview,
  useSubscriptions,
  useUnsubscribeFeeder,
  useUpdateMe,
} from "../hooks/queries";
import { Button } from "@/components/ui/button";
import { Card, CardTitle } from "@/components/ui/card";

export function Digest() {
  const { user, applyUser } = useAuth();
  const qc = useQueryClient();
  const subs = useSubscriptions();
  const preview = useDigestPreview();
  const unsubscribe = useUnsubscribeFeeder();
  // Changing frequency reshapes the trailing preview window → revalidate the preview.
  const updateMe = useUpdateMe((fresh) => {
    applyUser(fresh);
    qc.invalidateQueries({ queryKey: ["digest-preview"] });
  });

  return (
    <div className="absolute inset-0 overflow-y-auto">
      <div className="mx-auto flex w-full max-w-2xl flex-col gap-4 px-4 py-5">
        <header>
          <p className="font-mono text-[10px] uppercase tracking-[0.18em] text-faint">
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

        <Card className="flex flex-col gap-3">
          <CardTitle>Subscriptions</CardTitle>
          {subs.isLoading ? (
            <p className="text-muted-foreground">Loading…</p>
          ) : subs.data && subs.data.length === 0 ? (
            <p className="text-muted-foreground">
              You're not subscribed to anyone yet. Find people in the Directory.
            </p>
          ) : (
            <ul className="flex flex-col divide-y divide-border">
              {subs.data?.map((s) => (
                <li className="flex items-center gap-3 py-3 first:pt-0 last:pb-0" key={s.feeder_id}>
                  <div className="flex min-w-0 flex-1 flex-col gap-1">
                    <span className="font-semibold">{s.display_name ?? "Unnamed"}</span>
                    <Platforms platforms={s.platforms} />
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
          )}
        </Card>

        <Card className="flex flex-col gap-3">
          <CardTitle>Preview</CardTitle>
          <p className="text-sm text-muted-foreground">
            A representative sample of what your next digest will look like.
          </p>
        {preview.isLoading ? (
          <p className="muted">Loading preview…</p>
        ) : preview.isError ? (
          <p className="error">Couldn't load the preview.</p>
        ) : !preview.data ? null : preview.data.feeders.length === 0 &&
          preview.data.quiet_feeders.length === 0 ? (
          <p className="muted">
            Nothing to preview yet — follow some people with recent posts.
          </p>
        ) : (
          <div className="digest-preview">
            {/* Mirrors the email: compact (one line per feeder) once many are active,
                else the spacious group-by-source layout. */}
            {preview.data.compact ? (
              <ul className="compact-list">
                {preview.data.feeders.map((f) => (
                  <CompactRow key={f.feeder_id} feeder={f} />
                ))}
              </ul>
            ) : (
              preview.data.feeders.map((f) => (
                <FeederBlock key={f.feeder_id} feeder={f} />
              ))
            )}
            {preview.data.quiet_feeders.length > 0 && (
              <div className="quiet-block">
                <div className="muted small">No updates</div>
                <p className="muted small">
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
    <div className="feeder-block">
      <h3>From {feeder.display_name ?? "Unnamed"}</h3>
      {feeder.sources.map((source, si) => (
        <div className="source-block" key={`src-${si}`}>
          <div className="source-label">{source.label}</div>
          {source.longs.map((item, i) => (
            <LongItem key={`l-${i}`} item={item} />
          ))}
          {source.shorts.length > 0 && (
            <ul className="shorts-list">
              {source.shorts.map((item, i) => (
                <li key={`s-${i}`}>
                  <a href={item.url} target="_blank" rel="noreferrer noopener">
                    {shortText(item)}
                  </a>
                </li>
              ))}
            </ul>
          )}
        </div>
      ))}
    </div>
  );
}

// Compact format: one line per feeder, showing its single representative item.
function CompactRow({ feeder }: { feeder: DigestFeeder }) {
  const item = feeder.selected;
  const label = item.title ?? item.text ?? item.excerpt ?? item.url;
  return (
    <li className="compact-row">
      <span className="compact-who">{feeder.display_name ?? "Unnamed"}</span>
      <a href={item.url} target="_blank" rel="noreferrer noopener">
        {label.length > 100 ? `${label.slice(0, 100)}…` : label}
      </a>
    </li>
  );
}

function LongItem({ item }: { item: DigestItem }) {
  return (
    <div className="long-item">
      <a className="long-title" href={item.url} target="_blank" rel="noreferrer noopener">
        {item.title ?? item.url}
      </a>
      {item.excerpt && <p className="excerpt">{item.excerpt}</p>}
    </div>
  );
}

function shortText(item: DigestItem): string {
  const body = item.text ?? item.title ?? item.url;
  return body.length > 100 ? `${body.slice(0, 100)}…` : body;
}
