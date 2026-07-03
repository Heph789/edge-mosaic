import type { Link, ProfileSource } from "../api";

// Feeds we could actually scrape stay in the Feeds list; ones we couldn't (yet) are folded
// into the plain Links section instead of being flagged inline as "unverified".
export function splitSources(sources: ProfileSource[]): {
  feeds: ProfileSource[];
  unscrapableLinks: Link[];
} {
  const feeds: ProfileSource[] = [];
  const unscrapableLinks: Link[] = [];
  for (const s of sources) {
    if (s.status === "unverified") {
      unscrapableLinks.push({ label: s.title ?? s.label, url: s.url });
    } else {
      feeds.push(s);
    }
  }
  return { feeds, unscrapableLinks };
}
