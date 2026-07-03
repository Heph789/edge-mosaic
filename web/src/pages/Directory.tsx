import { memo, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { Crosshair, Search } from "lucide-react";
import type { Discover, Link, MosaicTile as MosaicRow, PlatformPill } from "../api";
import { useAllDiscover, useMosaic, useToggleSubscribeAll } from "../hooks/queries";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Input } from "@/components/ui/input";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { SubscribeButton } from "@/components/SubscribeButton";
import { cn } from "@/lib/utils";
import { generatedTileBackground, initialsOf, spiral } from "@/lib/mosaic";

const TILE = 106;

type View = "mosaic" | "list";

export function Directory() {
  const [view, setView] = useState<View>("mosaic");
  const [query, setQuery] = useState("");
  // The mosaic paints from a one-request manifest; the list's richer rows (bio, pills,
  // subscribe state) page through /discover — but only once the list view is opened.
  const mosaic = useMosaic();
  const list = useAllDiscover(view === "list");
  const toggle = useToggleSubscribeAll();
  const navigate = useNavigate();
  const location = useLocation();

  const members = list.data ?? [];

  // Only the row whose mutation is in flight is "pending" — a shared toggle.isPending would
  // dim every Subscribe button at once.
  const mutate = toggle.mutate;
  const pendingId = toggle.isPending ? toggle.variables?.userId ?? null : null;

  // Stable callbacks so memoized rows only re-render when their own data changes.
  const openProfile = useCallback(
    (username: string) => {
      navigate(`/p/${username}`, { state: { backgroundLocation: location } });
    },
    [navigate, location]
  );
  const onToggle = useCallback(
    (userId: number, subscribe: boolean) => mutate({ userId, subscribe }),
    [mutate]
  );

  return (
    <div className="absolute inset-0 flex flex-col bg-background">
      <header className="z-10 shrink-0 border-b border-border bg-card px-4 pt-4 pb-3">
        <div className="flex items-center justify-between gap-3">
          <h1 className="font-display text-xl font-bold leading-tight tracking-tight">
            Edge Mosaic
          </h1>
          <div className="flex items-center gap-2">
            <Tabs value={view} onValueChange={(v) => setView(v as View)}>
              <TabsList className="h-9">
                <TabsTrigger value="mosaic" className="text-xs">Mosaic</TabsTrigger>
                <TabsTrigger value="list" className="text-xs">List</TabsTrigger>
              </TabsList>
            </Tabs>
          </div>
        </div>
        {/* Search is available from either view; typing while in the mosaic flips to the
            list, which is where results are filtered and scannable. */}
        <div className="relative mt-3">
          <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            type="search"
            value={query}
            onChange={(e) => {
              const next = e.target.value;
              setQuery(next);
              if (next && view === "mosaic") setView("list");
            }}
            placeholder="Search by name or city…"
            className="rounded-full pl-9"
          />
        </div>
      </header>

      <div className="min-h-0 flex-1">
        {view === "mosaic" ? (
          mosaic.isError ? (
            <CenterNote>Couldn't load the directory. Try again.</CenterNote>
          ) : mosaic.isLoading ? (
            <CenterNote>Loading the mosaic…</CenterNote>
          ) : (
            <Mosaic tiles={mosaic.data ?? []} onOpen={openProfile} />
          )
        ) : list.isError ? (
          <CenterNote>Couldn't load the directory. Try again.</CenterNote>
        ) : list.isLoading ? (
          <CenterNote>Loading the directory…</CenterNote>
        ) : (
          <ListView
            members={members}
            query={query}
            pendingId={pendingId}
            onOpen={openProfile}
            onToggle={onToggle}
          />
        )}
      </div>
    </div>
  );
}

function CenterNote({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex h-full items-center justify-center px-6 text-center text-muted-foreground">
      {children}
    </div>
  );
}

// ----------------------------------------------------------------------------------------
// Mosaic: a drag-to-pan canvas. Real-photo tiles cluster at the centre (assigned the first
// spiral cells); initials-only tiles ring outward.
//
// Every tile mounts immediately (gradient + initials are pure CSS), but profile photos
// hydrate lazily: a trickle scheduler mounts <img>s in small batches, nearest to the
// current viewport centre first, and re-prioritizes as the user pans. Only tiles within
// HYDRATE_REACH viewports of the centre load at all, so roaming — not mounting — is what
// pulls in the far edges of the wall.
// ----------------------------------------------------------------------------------------
const HYDRATE_BATCH = 24; // images mounted per tick — fills a desktop viewport in a few ticks
const HYDRATE_TICK_MS = 90;
const HYDRATE_REACH = 1.25; // load radius, in viewport-max-dimensions from the view centre

function Mosaic({
  tiles,
  onOpen,
}: {
  tiles: MosaicRow[];
  onOpen: (username: string) => void;
}) {
  const viewportRef = useRef<HTMLDivElement | null>(null);
  const canvasRef = useRef<HTMLDivElement | null>(null);
  const offset = useRef({ x: 0, y: 0 });
  const start = useRef<{ x: number; y: number; ox: number; oy: number } | null>(null);
  const moved = useRef(false);
  const rafRef = useRef<number | null>(null);
  const recentMoves = useRef<{ x: number; y: number; t: number }[]>([]);
  const [dragging, setDragging] = useState(false);
  const [centered, setCentered] = useState(false);
  // user_ids whose photo is mounted. Grows monotonically — once loaded, an image stays.
  const [hydrated, setHydrated] = useState<ReadonlySet<number>>(() => new Set<number>());
  const hydratedRef = useRef(hydrated);
  hydratedRef.current = hydrated;
  const hydrateTimer = useRef<number | null>(null);

  // Real-photo members first → they take the innermost spiral cells.
  const placed = useMemo(() => {
    const sorted = [...tiles].sort(
      (a, b) => Number(!!b.profile_image_url) - Number(!!a.profile_image_url)
    );
    const cells = spiral(sorted.length);
    let extent = 0;
    const placedTiles = sorted.map((m, i) => {
      const px = cells[i].x;
      const py = cells[i].y;
      extent = Math.max(extent, Math.abs(px), Math.abs(py));
      return { m, px, py };
    });
    return { tiles: placedTiles, extent: extent + TILE };
  }, [tiles]);

  // Only tiles with a photo cost network — the hydration queue ignores the rest.
  const photoTiles = useMemo(
    () => placed.tiles.filter((t) => t.m.profile_image_url),
    [placed]
  );

  // Mount the next batch of photos, nearest to the current view centre first. Reschedules
  // itself until everything within reach is in; panning re-runs it against the new centre.
  function hydratePass() {
    hydrateTimer.current = null;
    const vp = viewportRef.current;
    if (!vp) return;
    // Viewport centre in canvas coordinates (the canvas is translated by `offset`).
    const cx = vp.clientWidth / 2 - offset.current.x;
    const cy = vp.clientHeight / 2 - offset.current.y;
    const reach = Math.max(vp.clientWidth, vp.clientHeight) * HYDRATE_REACH;
    const due = photoTiles
      .filter((t) => !hydratedRef.current.has(t.m.user_id))
      .map((t) => ({ id: t.m.user_id, d: Math.hypot(t.px - cx, t.py - cy) }))
      .filter((t) => t.d <= reach)
      .sort((a, b) => a.d - b.d)
      .slice(0, HYDRATE_BATCH);
    if (due.length === 0) return;
    setHydrated((prev) => {
      const next = new Set(prev);
      for (const t of due) next.add(t.id);
      return next;
    });
    scheduleHydrate();
  }

  function scheduleHydrate() {
    if (hydrateTimer.current !== null) return;
    hydrateTimer.current = window.setTimeout(hydratePass, HYDRATE_TICK_MS);
  }

  function applyTransform() {
    const cv = canvasRef.current;
    if (cv) cv.style.transform = `translate3d(${offset.current.x}px, ${offset.current.y}px, 0)`;
    // Every pan path funnels through here, so this is the one hook needed to keep the
    // hydration queue pointed at wherever the user is looking.
    scheduleHydrate();
  }

  function clamp(x: number, y: number) {
    const vp = viewportRef.current;
    if (!vp) return { x, y };
    const margin = 90;
    const ext = placed.extent;
    const maxX = vp.clientWidth - margin + ext;
    const minX = margin - ext;
    const maxY = vp.clientHeight - margin + ext;
    const minY = margin - ext;
    return {
      x: Math.max(minX, Math.min(maxX, x)),
      y: Math.max(minY, Math.min(maxY, y)),
    };
  }

  // Centre the spiral origin in the viewport on first layout, then hydrate the first
  // wave of photos immediately (the scheduler takes over from there).
  useEffect(() => {
    const vp = viewportRef.current;
    if (!vp || centered) return;
    offset.current = { x: vp.clientWidth / 2, y: vp.clientHeight / 2 };
    applyTransform();
    hydratePass();
    setCentered(true);
  }, [centered, placed]);

  function cancelMomentum() {
    if (rafRef.current !== null) {
      cancelAnimationFrame(rafRef.current);
      rafRef.current = null;
    }
  }

  function startMomentum(vx: number, vy: number) {
    cancelMomentum();
    const FRICTION = 0.91;
    function step() {
      vx *= FRICTION;
      vy *= FRICTION;
      if (Math.abs(vx) < 0.3 && Math.abs(vy) < 0.3) { rafRef.current = null; return; }
      offset.current = clamp(offset.current.x + vx, offset.current.y + vy);
      applyTransform();
      rafRef.current = requestAnimationFrame(step);
    }
    rafRef.current = requestAnimationFrame(step);
  }

  function onPointerDown(e: React.PointerEvent) {
    if (e.button != null && e.button !== 0) return;
    cancelMomentum();
    recentMoves.current = [];
    start.current = { x: e.clientX, y: e.clientY, ox: offset.current.x, oy: offset.current.y };
    moved.current = false;
    setDragging(true);
    window.addEventListener("pointermove", onPointerMove);
    window.addEventListener("pointerup", onPointerUp);
  }
  function onPointerMove(e: PointerEvent) {
    const s = start.current;
    if (!s) return;
    const now = performance.now();
    recentMoves.current.push({ x: e.clientX, y: e.clientY, t: now });
    recentMoves.current = recentMoves.current.filter((m) => now - m.t < 80);
    const dx = e.clientX - s.x;
    const dy = e.clientY - s.y;
    if (Math.abs(dx) > 4 || Math.abs(dy) > 4) moved.current = true;
    offset.current = clamp(s.ox + dx, s.oy + dy);
    applyTransform();
  }
  function onPointerUp() {
    window.removeEventListener("pointermove", onPointerMove);
    window.removeEventListener("pointerup", onPointerUp);
    start.current = null;
    setDragging(false);
    const moves = recentMoves.current;
    if (moves.length >= 2) {
      const first = moves[0];
      const last = moves[moves.length - 1];
      const dt = last.t - first.t;
      if (dt > 0 && dt < 80) {
        const vx = ((last.x - first.x) / dt) * 16;
        const vy = ((last.y - first.y) / dt) * 16;
        if (Math.abs(vx) > 1 || Math.abs(vy) > 1) startMomentum(vx, vy);
      }
    }
    recentMoves.current = [];
  }

  // Trackpad scroll-to-pan (non-passive so preventDefault works).
  useEffect(() => {
    const vp = viewportRef.current;
    if (!vp) return;
    function onWheel(e: WheelEvent) {
      e.preventDefault();
      cancelMomentum();
      offset.current = clamp(offset.current.x - e.deltaX, offset.current.y - e.deltaY);
      applyTransform();
    }
    vp.addEventListener("wheel", onWheel, { passive: false });
    return () => vp.removeEventListener("wheel", onWheel);
  }, [placed]);

  useEffect(
    () => () => {
      window.removeEventListener("pointermove", onPointerMove);
      window.removeEventListener("pointerup", onPointerUp);
      cancelMomentum();
      if (hydrateTimer.current !== null) window.clearTimeout(hydrateTimer.current);
    },
    []
  );

  function recenter() {
    const vp = viewportRef.current;
    if (!vp) return;
    offset.current = { x: vp.clientWidth / 2, y: vp.clientHeight / 2 };
    applyTransform();
  }

  // Stable callback (drag-vs-tap check lives here) so memoized tiles never re-render
  // just because a hydration batch landed elsewhere on the wall.
  const handleOpen = useCallback(
    (username: string) => {
      if (!moved.current) onOpen(username);
    },
    [onOpen]
  );

  if (tiles.length === 0)
    return <CenterNote>No one to show yet.</CenterNote>;

  return (
    <div
      ref={viewportRef}
      className="mosaic-viewport relative h-full w-full overflow-hidden"
      data-dragging={dragging ? "true" : "false"}
      onPointerDown={onPointerDown}
    >
      <div ref={canvasRef} className="mosaic-canvas absolute left-0 top-0 h-0 w-0">
        {placed.tiles.map(({ m, px, py }) => (
          <MosaicTileView
            key={m.user_id}
            tile={m}
            left={px - TILE / 2}
            top={py - TILE / 2}
            showImage={hydrated.has(m.user_id)}
            onOpen={handleOpen}
          />
        ))}
      </div>
      <button
        type="button"
        onClick={recenter}
        className="absolute bottom-10 right-4 flex items-center gap-1.5 rounded-full border border-border bg-card/90 px-3 py-1.5 font-mono text-[11px] lg:text-[13px] text-faint shadow-sm backdrop-blur-sm transition-colors hover:text-foreground"
      >
        <Crosshair className="size-3.5" />
        Center
      </button>
      <div className="mosaic-hint pointer-events-none absolute inset-x-0 bottom-3 text-center font-mono text-[11px] lg:text-[13px] text-faint">
        drag to roam · tap a tile to open
      </div>
    </div>
  );
}

const MosaicTileView = memo(function MosaicTileView({
  tile,
  left,
  top,
  showImage,
  onOpen,
}: {
  tile: MosaicRow;
  left: number;
  top: number;
  showImage: boolean; // hydration gate — the photo only mounts once the scheduler says so
  onOpen: (username: string) => void;
}) {
  const name = tile.display_name ?? "Unnamed";
  return (
    <button
      type="button"
      onClick={() => onOpen(tile.username)}
      className={`mosaic-tile absolute overflow-hidden rounded-md border border-border text-left shadow-sm${
        tile.placeholder ? " opacity-50" : ""
      }`}
      style={{ left, top, width: TILE, height: TILE }}
    >
      {/* The generated gradient + initials sit underneath as the base layer. A photo
          overlays them; if it fails to load, onError hides the <img> and they show through. */}
      <span
        className="flex h-full w-full items-center justify-center font-mono text-xl font-semibold text-ink/45"
        style={{ background: generatedTileBackground(tile.username) }}
      >
        {initialsOf(tile.display_name, tile.username)}
      </span>
      {tile.profile_image_url && showImage && (
        <img
          src={tile.profile_image_url}
          alt=""
          draggable={false}
          decoding="async"
          className="absolute inset-0 h-full w-full object-cover"
          onError={(e) => {
            e.currentTarget.style.display = "none";
          }}
        />
      )}
      <span className="pointer-events-none absolute inset-x-0 bottom-0 bg-gradient-to-t from-ink/85 to-transparent px-2 pb-1.5 pt-5">
        <span className="block truncate text-[13px] lg:text-[16px] font-semibold leading-tight text-white">
          {name}
        </span>
      </span>
    </button>
  );
});

// ----------------------------------------------------------------------------------------
// List: searchable, scannable rows.
// ----------------------------------------------------------------------------------------
function ListView({
  members,
  query,
  pendingId,
  onOpen,
  onToggle,
}: {
  members: Discover[];
  query: string;
  pendingId: number | null;
  onOpen: (username: string) => void;
  onToggle: (userId: number, subscribe: boolean) => void;
}) {
  const term = query.trim().toLowerCase();
  const filtered = term
    ? members.filter((m) =>
        [m.display_name, m.username, m.city, m.bio]
          .filter(Boolean)
          .some((f) => (f as string).toLowerCase().includes(term))
      )
    : members;

  if (filtered.length === 0)
    return (
      <CenterNote>
        {term ? `No one matches “${query}”.` : "No one to show yet."}
      </CenterNote>
    );

  return (
    <div className="h-full overflow-y-auto px-4 py-4">
      <ul className="mx-auto flex max-w-2xl flex-col gap-2.5">
        {filtered.map((m) => (
          <ListRow
            key={m.user_id}
            row={m}
            pending={m.user_id === pendingId}
            onOpen={onOpen}
            onToggle={onToggle}
          />
        ))}
      </ul>
    </div>
  );
}

const ListRow = memo(function ListRow({
  row,
  pending,
  onOpen,
  onToggle,
}: {
  row: Discover;
  pending: boolean;
  onOpen: (username: string) => void;
  onToggle: (userId: number, subscribe: boolean) => void;
}) {
  const name = row.display_name ?? "Unnamed";
  return (
    <li className="rounded-xl border border-border bg-card p-4 transition-shadow hover:shadow-[0_4px_16px_rgba(20,16,10,0.06)]">
      <div className="flex items-start gap-3">
        <button
          type="button"
          onClick={() => onOpen(row.username)}
          className="flex min-w-0 flex-1 items-start gap-3 text-left"
        >
          <Avatar className="size-12 border border-border">
            {row.profile_image_url && <AvatarImage src={row.profile_image_url} alt="" />}
            <AvatarFallback>{initialsOf(row.display_name, row.username)}</AvatarFallback>
          </Avatar>
          <div className="min-w-0 flex-1">
            <div>
              <span className="font-semibold leading-tight">{name}</span>
              {row.city && (
                <p className="font-mono text-[11px] lg:text-[13px] text-faint">{row.city}</p>
              )}
            </div>
            {row.bio && (
              <p className="mt-1 line-clamp-2 text-sm text-muted-foreground">{row.bio}</p>
            )}
          </div>
        </button>
        <SubscribeButton
          hasFeeders={row.platforms.length > 0}
          isSubscribed={row.is_subscribed}
          pending={pending}
          onToggle={(subscribe) => onToggle(row.user_id, subscribe)}
          name={row.display_name}
          className="shrink-0"
          size="sm"
        />
      </div>
      <Pills platforms={row.platforms} links={row.links} className="mt-3 pl-[3.75rem]" />
    </li>
  );
});

// ----------------------------------------------------------------------------------------
// Pills — feeder-source pills (link out) + non-feeder profile links.
// ----------------------------------------------------------------------------------------
const pillClass =
  "inline-flex items-center rounded-full border px-2.5 py-1 font-mono text-[11px] lg:text-[13px] transition-colors";

export function Pills({
  platforms,
  links,
  className,
}: {
  platforms: PlatformPill[];
  links: Link[];
  className?: string;
}) {
  if (platforms.length === 0 && links.length === 0)
    return (
      <span className={cn("text-sm text-muted-foreground", className)}>
        no sources yet
      </span>
    );
  return (
    <div className={cn("flex flex-wrap gap-1.5", className)}>
      {platforms.map((p) => (
        <a
          key={`p:${p.label}`}
          className={cn(pillClass, "border-border bg-secondary text-foreground hover:border-marigold")}
          href={p.url}
          target="_blank"
          rel="noreferrer noopener"
          onClick={(e) => e.stopPropagation()}
        >
          {p.label}
        </a>
      ))}
      {links.map((l, i) => (
        <a
          key={`l:${i}`}
          className={cn(pillClass, "border-border bg-transparent text-muted-foreground hover:border-marigold hover:text-foreground")}
          href={l.url}
          target="_blank"
          rel="noreferrer noopener"
          onClick={(e) => e.stopPropagation()}
        >
          {l.label}
        </a>
      ))}
    </div>
  );
}
