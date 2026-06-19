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
    <div className="page stack">
      <h1>Digest</h1>

      <section className="card stack">
        <h2>Delivery settings</h2>
        <div className="settings-row">
          <label className="field inline">
            <span>Frequency</span>
            <select
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
          <label className="field inline checkbox">
            <input
              type="checkbox"
              checked={user?.digest_paused ?? false}
              disabled={updateMe.isPending}
              onChange={(e) => updateMe.mutate({ digest_paused: e.target.checked })}
            />
            <span>Pause digest emails</span>
          </label>
        </div>
      </section>

      <section className="card stack">
        <h2>Following</h2>
        {subs.isLoading ? (
          <p className="muted">Loading…</p>
        ) : subs.data && subs.data.length === 0 ? (
          <p className="muted">
            You're not following anyone yet. Find people in the Directory.
          </p>
        ) : (
          <ul className="list">
            {subs.data?.map((s) => (
              <li className="row" key={s.feeder_id}>
                <div className="row-main">
                  <span className="row-name">{s.display_name ?? "Unnamed"}</span>
                  <Platforms platforms={s.platforms} />
                </div>
                <button
                  className="btn btn-ghost"
                  disabled={unsubscribe.isPending}
                  onClick={() => unsubscribe.mutate(s.feeder_id)}
                >
                  Unfollow
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="card stack">
        <h2>Preview</h2>
        <p className="muted small">
          A representative sample of what your next digest will look like.
        </p>
        {preview.isLoading ? (
          <p className="muted">Loading preview…</p>
        ) : preview.isError ? (
          <p className="error">Couldn't load the preview.</p>
        ) : preview.data && preview.data.feeders.length === 0 ? (
          <p className="muted">
            Nothing to preview yet — follow some people with recent posts.
          </p>
        ) : (
          <div className="digest-preview">
            {preview.data?.feeders.map((f) => (
              <FeederBlock key={f.feeder_id} feeder={f} />
            ))}
          </div>
        )}
      </section>
    </div>
  );
}

// Mirrors the email layout. All scraped strings render as text (React escapes by
// default) — NEVER dangerouslySetInnerHTML on feed/Bluesky content (XSS rule, §2).
function FeederBlock({ feeder }: { feeder: DigestFeeder }) {
  return (
    <div className="feeder-block">
      <h3>From {feeder.display_name ?? "Unnamed"}</h3>
      {feeder.longs.map((item, i) => (
        <LongItem key={`l-${i}`} item={item} />
      ))}
      {feeder.shorts.length > 0 && (
        <div className="shorts">
          <div className="muted small">Also posted</div>
          <ul className="shorts-list">
            {feeder.shorts.map((item, i) => (
              <li key={`s-${i}`}>
                <a href={item.url} target="_blank" rel="noreferrer noopener">
                  {shortText(item)}
                </a>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
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
