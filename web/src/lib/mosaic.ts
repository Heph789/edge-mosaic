// Pure helpers for the Directory mosaic: initials for members without a photo, and a
// square-spiral layout so the densest (real-photo) tiles sit in the middle and the wall
// radiates outward.

export function initialsOf(name: string | null, fallback: string): string {
  const src = (name ?? "").trim();
  if (!src) return (fallback.trim().charAt(0) || "?").toUpperCase();
  const parts = src.split(/\s+/).filter(Boolean);
  const first = parts[0]?.charAt(0) ?? "";
  const second = parts.length > 1 ? parts[parts.length - 1].charAt(0) : "";
  return (first + second).toUpperCase() || "?";
}

function hashStr(s: string): number {
  let h = 0;
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) | 0;
  return Math.abs(h);
}

// Warm, varied gradients seeded by username. Palette orbits marigold — terra cottas,
// ambers, sages, warm clay — so generated tiles feel alive rather than grey.
export function generatedTileBackground(seed: string): string {
  const h = hashStr(seed);
  const palettes = [
    { hue: 38, sat: 62, l1: 78, l2: 58 },  // marigold amber
    { hue: 25, sat: 55, l1: 74, l2: 56 },  // terra cotta
    { hue: 50, sat: 52, l1: 80, l2: 62 },  // golden straw
    { hue: 14, sat: 48, l1: 72, l2: 54 },  // burnt sienna
    { hue: 82, sat: 28, l1: 72, l2: 56 },  // sage
    { hue: 32, sat: 44, l1: 76, l2: 58 },  // warm clay
    { hue: 44, sat: 58, l1: 82, l2: 64 },  // honey
  ];
  const p = palettes[h % palettes.length];
  const angle = 110 + (h % 80);
  const l1 = p.l1 + (h % 6);
  const l2 = p.l2 + ((h >> 3) % 6);
  return `linear-gradient(${angle}deg, hsl(${p.hue} ${p.sat}% ${l1}%), hsl(${p.hue} ${p.sat}% ${l2}%))`;
}

export type SpiralCell = { x: number; y: number };

const CELL = 120; // must match Directory.tsx (TILE + gap)

// Brick-row grid: tiles in neat rows with alternating half-cell horizontal offset.
// Returns pixel offsets from the grid center, sorted nearest-first so real-photo
// members (assigned index 0…k) cluster at the middle of the wall.
export function spiral(n: number): SpiralCell[] {
  if (n === 0) return [];
  const cols = Math.max(4, Math.ceil(Math.sqrt(n) * 1.4));
  const rows = Math.ceil(n / cols);
  const centerX = ((cols - 1) * CELL) / 2;
  const centerY = ((rows - 1) * CELL) / 2;

  const all: Array<{ x: number; y: number; dist: number }> = [];
  for (let r = 0; r < rows; r++) {
    const rowOffset = r % 2 === 0 ? 0 : CELL / 2;
    for (let c = 0; c < cols; c++) {
      const x = c * CELL + rowOffset - centerX;
      const y = r * CELL - centerY;
      const dist = Math.sqrt(x * x + y * y);
      all.push({ x, y, dist });
    }
  }

  all.sort((a, b) => a.dist - b.dist);
  return all.slice(0, n).map(({ x, y }) => ({ x, y }));
}

// Small deterministic jitter (in px) so the grid reads as an organic wall, not a table.
export function jitter(seed: string, range: number): { jx: number; jy: number } {
  const h = hashStr(seed + "j");
  return {
    jx: ((h % 1000) / 1000 - 0.5) * range,
    jy: (((h >> 5) % 1000) / 1000 - 0.5) * range,
  };
}
