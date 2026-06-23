// A small "⚠" badge shown next to a feeder source we couldn't scrape yet. It's hoverable
// on desktop (native title tooltip) and pressable on mobile (tap toggles an inline note),
// so the explanation is reachable without a pointer.
import { useState } from "react";

const NOTE =
  "We couldn't read a feed from this link yet, so it shows on your profile but won't appear " +
  "in your followers' digests. We'll keep trying — it starts counting once it can be scraped.";

export function UnverifiedBadge() {
  const [open, setOpen] = useState(false);
  return (
    <span className="unverified-badge">
      <button
        type="button"
        className="pill pill-warning"
        title={NOTE}
        aria-label={NOTE}
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
      >
        ⚠ Can't scrape yet
      </button>
      {open && <span className="unverified-note muted small">{NOTE}</span>}
    </span>
  );
}
