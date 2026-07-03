import { useEffect, useRef, useState } from "react";
import { CircleHelp } from "lucide-react";

// Small info affordance that opens an explanatory note: hover/focus reveals it on desktop,
// tap-to-toggle plus an outside-click/tap dismiss covers mobile (mirrors UnverifiedBadge's
// approach so the explanation is reachable without a pointer).
export function InfoTooltip({ note }: { note: string }) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLSpanElement>(null);

  useEffect(() => {
    if (!open) return;
    function onPointerDown(e: PointerEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("pointerdown", onPointerDown);
    return () => document.removeEventListener("pointerdown", onPointerDown);
  }, [open]);

  return (
    <span ref={ref} className="group relative inline-flex">
      <button
        type="button"
        aria-label={note}
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        className="text-faint transition-colors hover:text-muted-foreground focus:outline-none"
      >
        <CircleHelp className="size-3.5" />
      </button>
      <span
        className={`absolute left-0 top-full z-10 mt-1.5 w-48 max-w-[70vw] rounded-md border border-border bg-popover p-2 text-[11px] lg:text-[13px] normal-case leading-snug tracking-normal text-popover-foreground shadow-md group-hover:block group-focus-within:block ${
          open ? "block" : "hidden"
        }`}
      >
        {note}
      </span>
    </span>
  );
}
