// Add / list / remove feed sources. Extracted from Profile so the onboarding wizard and
// the Profile page share one implementation. Typing or pasting a URL auto-triggers
// verification (debounced); confirm validates client-side. If the feed can't be read we
// don't block — the source is still added (as 'unverified') so it shows on the profile
// with a warning, just not in followers' digests.
import { useState, useEffect, useRef } from "react";
import { api, ApiError, type SourcePreview } from "../api";
import { useAddSource, useDeleteSource, useSources } from "../hooks/queries";
import { UnverifiedBadge } from "./UnverifiedBadge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

type AddState =
  | { step: "idle" }
  | { step: "debouncing" }
  | { step: "previewing" }
  | { step: "confirm"; preview: SourcePreview }
  // Preview couldn't read a feed. The user can still add it — same "Add source" action,
  // it just lands as 'unverified'.
  | { step: "warn"; message: string }
  | { step: "adding" };

export function SourcesEditor({
  onVerifying,
  hideHint = false,
}: {
  onVerifying?: (v: boolean) => void;
  hideHint?: boolean;
} = {}) {
  const sources = useSources();
  const addSource = useAddSource();
  const deleteSource = useDeleteSource();

  const [url, setUrl] = useState("");
  const [state, setState] = useState<AddState>({ step: "idle" });
  const [error, setError] = useState<string | null>(null);

  const verifyIdRef = useRef(0);

  const busy = state.step === "adding";
  const substackProfile = isSubstackProfileUrl(url);

  useEffect(() => {
    const trimmed = url.trim();
    if (!trimmed) {
      setState((s) => (s.step !== "adding" ? { step: "idle" } : s));
      return;
    }
    setState((s) => (s.step === "adding" ? s : { step: "debouncing" }));
    const myId = ++verifyIdRef.current;
    const timer = setTimeout(async () => {
      setState({ step: "previewing" });
      setError(null);
      try {
        const preview = await api.previewSource(trimmed);
        if (verifyIdRef.current !== myId) return;
        setState({ step: "confirm", preview });
      } catch (err) {
        if (verifyIdRef.current !== myId) return;
        setState({ step: "warn", message: errorText(err) });
      }
    }, 600);
    return () => clearTimeout(timer);
  }, [url]);

  useEffect(() => {
    onVerifying?.(url.trim().length > 0);
  }, [url, onVerifying]);

  async function onAdd() {
    if (state.step !== "confirm" && state.step !== "warn") return;
    setError(null);
    setState({ step: "adding" });
    try {
      await addSource.mutateAsync(url.trim());
      setUrl("");
      setState({ step: "idle" });
    } catch (err) {
      setState({ step: "warn", message: errorText(err) });
      setError(errorText(err));
    }
  }

  function onCancel() {
    setUrl("");
    setState({ step: "idle" });
    setError(null);
  }

  return (
    <div className="flex flex-col gap-3">
      {!hideHint && (
        <p className="text-sm text-muted-foreground">
          Paste a blog/Substack RSS URL, a Bluesky handle, or an X profile.
        </p>
      )}

      <div className="flex flex-col gap-2 sm:flex-row">
        <Input
          placeholder="blog RSS, @handle.bsky.social, or x.com/username"
          value={url}
          onChange={(e) => {
            setUrl(e.target.value);
            setError(null);
          }}
          onBlur={(e) => setUrl(normalizeSourceUrl(e.target.value))}
          disabled={busy}
          className="flex-1"
        />
        {(state.step === "debouncing" || state.step === "previewing") && (
          <span className="self-center font-mono text-xs text-faint">Checking…</span>
        )}
      </div>

      {substackProfile && (
        <p className="text-sm text-muted-foreground">
          That looks like a Substack <strong>profile</strong>. To pull your posts, paste your{" "}
          <strong>publication</strong> URL instead — e.g.{" "}
          <code className="font-mono text-xs">yourname.substack.com</code>.
        </p>
      )}

      {error && <p className="text-xs text-destructive">{error}</p>}

      {state.step === "confirm" && (
        <div className="flex flex-col gap-3 rounded-lg border border-ring bg-secondary p-3">
          <p className="text-sm">
            <strong>{state.preview.label}</strong> — found {state.preview.found_count} recent{" "}
            {state.preview.found_count === 1 ? "post" : "posts"}
            {state.preview.latest_title && (
              <>, latest: <em>"{state.preview.latest_title}"</em></>
            )}.
          </p>
          <div className="flex gap-2">
            <Button size="sm" onClick={onAdd}>Add source</Button>
            <Button size="sm" variant="ghost" onClick={onCancel}>Cancel</Button>
          </div>
        </div>
      )}

      {state.step === "warn" && (
        <div className="flex flex-col gap-3 rounded-lg border border-amber-300 bg-amber-50 p-3">
          <div>
            <p className="text-sm font-semibold">⚠ We couldn't read a feed from that link yet.</p>
            <p className="mt-0.5 text-xs text-muted-foreground">
              You can still add it — it'll show on your profile, but won't appear in digests
              until we can scrape it.
            </p>
          </div>
          <div className="flex gap-2">
            <Button size="sm" onClick={onAdd}>Add source</Button>
            <Button size="sm" variant="ghost" onClick={onCancel}>Cancel</Button>
          </div>
        </div>
      )}

      {sources.isLoading ? (
        <p className="text-sm text-muted-foreground">Loading…</p>
      ) : sources.data && sources.data.length === 0 ? (
        <p className="text-sm text-muted-foreground">No sources yet.</p>
      ) : (
        <ul className="flex flex-col divide-y divide-border">
          {sources.data?.map((s) => (
            <li key={s.id} className="flex items-start gap-3 py-3 first:pt-0 last:pb-0">
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-semibold">{s.title ?? s.input_url}</p>
                <div className="mt-1 flex flex-wrap items-center gap-1.5">
                  <span className="rounded-full border border-border bg-secondary px-2 py-0.5 font-mono text-[10px] text-muted-foreground">
                    {s.label}
                  </span>
                  {s.status === "unverified" && <UnverifiedBadge />}
                  <span className={cn("font-mono text-[10px] text-faint", s.title && "truncate max-w-[180px]")}>
                    {s.input_url}
                  </span>
                </div>
              </div>
              <Button
                variant="ghost"
                size="sm"
                className="shrink-0"
                disabled={deleteSource.isPending}
                onClick={() => deleteSource.mutate(s.id)}
              >
                Remove
              </Button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function normalizeSourceUrl(url: string): string {
  const trimmed = url.trim();
  if (trimmed && !trimmed.startsWith("@") && !trimmed.includes("://"))
    return `https://${trimmed}`;
  return trimmed;
}

function isSubstackProfileUrl(raw: string): boolean {
  const trimmed = raw.trim();
  if (!trimmed || trimmed.startsWith("@")) return false;
  try {
    const u = new URL(trimmed.includes("://") ? trimmed : `https://${trimmed}`);
    const host = u.hostname.toLowerCase().replace(/^www\./, "");
    if (host !== "substack.com") return false;
    return u.pathname.startsWith("/@") || u.pathname.startsWith("/profile");
  } catch {
    return false;
  }
}

function errorText(err: unknown): string {
  if (err instanceof ApiError) return err.message;
  return "Something went wrong. Try again.";
}
