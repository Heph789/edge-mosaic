import { useEffect, useMemo, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { Crosshair, Search } from "lucide-react";
import type { Discover, Link, PlatformPill } from "../api";
import { useAllDiscover, useToggleSubscribeAll } from "../hooks/queries";
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
  const { data, isError, isLoading } = useAllDiscover();
  const toggle = useToggleSubscribeAll();
  const navigate = useNavigate();
  const location = useLocation();

  const members = data ?? [];

  function openProfile(username: string) {
    navigate(`/p/${username}`, { state: { backgroundLocation: location } });
  }
  function onToggle(row: Discover, subscribe: boolean) {
    toggle.mutate({ userId: row.user_id, subscribe });
  }

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
        {isError ? (
          <CenterNote>Couldn't load the directory. Try again.</CenterNote>
        ) : isLoading ? (
          <CenterNote>Loading the mosaic…</CenterNote>
        ) : view === "mosaic" ? (
          <Mosaic members={members} onOpen={openProfile} />
        ) : (
          <ListView
            members={members}
            query={query}
            pending={toggle.isPending}
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
// ----------------------------------------------------------------------------------------
function Mosaic({
  members,
  onOpen,
}: {
  members: Discover[];
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

  // Real-photo members first → they take the innermost spiral cells.
  const placed = useMemo(() => {
    const sorted = [...members].sort(
      (a, b) => Number(!!b.profile_image_url) - Number(!!a.profile_image_url)
    );
    const cells = spiral(sorted.length);
    let extent = 0;
    const tiles = sorted.map((m, i) => {
      const px = cells[i].x;
      const py = cells[i].y;
      extent = Math.max(extent, Math.abs(px), Math.abs(py));
      return { m, px, py };
    });
    return { tiles, extent: extent + TILE };
  }, [members]);

  function applyTransform() {
    const cv = canvasRef.current;
    if (cv) cv.style.transform = `translate3d(${offset.current.x}px, ${offset.current.y}px, 0)`;
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

  // Centre the spiral origin in the viewport on first layout.
  useEffect(() => {
    const vp = viewportRef.current;
    if (!vp || centered) return;
    offset.current = { x: vp.clientWidth / 2, y: vp.clientHeight / 2 };
    applyTransform();
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
    },
    []
  );

  function recenter() {
    const vp = viewportRef.current;
    if (!vp) return;
    offset.current = { x: vp.clientWidth / 2, y: vp.clientHeight / 2 };
    applyTransform();
  }

  if (members.length === 0)
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
          <MosaicTile
            key={m.user_id}
            row={m}
            left={px - TILE / 2}
            top={py - TILE / 2}
            onOpen={() => {
              if (!moved.current) onOpen(m.username);
            }}
          />
        ))}
      </div>
      <button
        type="button"
        onClick={recenter}
        className="absolute bottom-10 right-4 flex items-center gap-1.5 rounded-full border border-border bg-card/90 px-3 py-1.5 font-mono text-[11px] text-faint shadow-sm backdrop-blur-sm transition-colors hover:text-foreground"
      >
        <Crosshair className="size-3.5" />
        Center
      </button>
      <div className="mosaic-hint pointer-events-none absolute inset-x-0 bottom-3 text-center font-mono text-[11px] text-faint">
        drag to roam · tap a tile to open
      </div>
    </div>
  );
}

function MosaicTile({
  row,
  left,
  top,
  onOpen,
}: {
  row: Discover;
  left: number;
  top: number;
  onOpen: () => void;
}) {
  const name = row.display_name ?? "Unnamed";
  // Pre-seeded ghosts: no links at all (neither feeder sources nor profile links) and never
  // registered (unverified inbox). Fade these so live members read as the foreground.
  const isPlaceholder =
    !row.verified && row.links.length === 0 && row.platforms.length === 0;
  return (
    <button
      type="button"
      onClick={onOpen}
      className={`mosaic-tile absolute overflow-hidden rounded-md border border-border text-left shadow-sm${
        isPlaceholder ? " opacity-50" : ""
      }`}
      style={{ left, top, width: TILE, height: TILE }}
    >
      {/* The generated gradient + initials sit underneath as the base layer. A photo
          overlays them; if it fails to load, onError hides the <img> and they show through. */}
      <span
        className="flex h-full w-full items-center justify-center font-mono text-xl font-semibold text-ink/45"
        style={{ background: generatedTileBackground(row.username) }}
      >
        {initialsOf(row.display_name, row.username)}
      </span>
      {row.profile_image_url && (
        <img
          src={row.profile_image_url}
          alt=""
          draggable={false}
          className="absolute inset-0 h-full w-full object-cover"
          onError={(e) => {
            e.currentTarget.style.display = "none";
          }}
        />
      )}
      <span className="pointer-events-none absolute inset-x-0 bottom-0 bg-gradient-to-t from-ink/85 to-transparent px-2 pb-1.5 pt-5">
        <span className="block truncate text-[13px] font-semibold leading-tight text-white">
          {name}
        </span>
      </span>
    </button>
  );
}

// ----------------------------------------------------------------------------------------
// List: searchable, scannable rows.
// ----------------------------------------------------------------------------------------
function ListView({
  members,
  query,
  pending,
  onOpen,
  onToggle,
}: {
  members: Discover[];
  query: string;
  pending: boolean;
  onOpen: (username: string) => void;
  onToggle: (row: Discover, subscribe: boolean) => void;
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
            pending={pending}
            onOpen={() => onOpen(m.username)}
            onToggle={(subscribe) => onToggle(m, subscribe)}
          />
        ))}
      </ul>
    </div>
  );
}

function ListRow({
  row,
  pending,
  onOpen,
  onToggle,
}: {
  row: Discover;
  pending: boolean;
  onOpen: () => void;
  onToggle: (subscribe: boolean) => void;
}) {
  const name = row.display_name ?? "Unnamed";
  return (
    <li className="rounded-xl border border-border bg-card p-4 transition-shadow hover:shadow-[0_4px_16px_rgba(20,16,10,0.06)]">
      <div className="flex items-start gap-3">
        <button
          type="button"
          onClick={onOpen}
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
                <p className="font-mono text-[11px] text-faint">{row.city}</p>
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
          onToggle={onToggle}
          name={row.display_name}
          className="shrink-0"
          size="sm"
        />
      </div>
      <Pills platforms={row.platforms} links={row.links} className="mt-3 pl-[3.75rem]" />
    </li>
  );
}

// ----------------------------------------------------------------------------------------
// Pills — feeder-source pills (link out) + non-feeder profile links.
// ----------------------------------------------------------------------------------------
const pillClass =
  "inline-flex items-center rounded-full border px-2.5 py-1 font-mono text-[11px] transition-colors";

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

// Static platform pills (no links) — used by the Digest tab's subscription list.
export function Platforms({ platforms }: { platforms: string[] }) {
  if (platforms.length === 0)
    return <span className="text-sm text-muted-foreground">no sources yet</span>;
  return (
    <div className="flex flex-wrap gap-1.5">
      {platforms.map((p) => (
        <span
          key={p}
          className={cn(pillClass, "border-border bg-secondary text-muted-foreground")}
        >
          {p}
        </span>
      ))}
    </div>
  );
}
