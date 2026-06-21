// Typed fetch client mirrored by hand from the API's /openapi.json (no codegen).
// One choke point (`request`) attaches the bearer token and enforces the global
// 401 → clear-token-and-redirect rule (covers the fixed 30-day session expiry).

const API_URL = import.meta.env.VITE_API_URL ?? "http://localhost:8000";

// Bearer token storage key. auth.tsx reads/writes the same key.
export const TOKEN_KEY = "em_token";

// --- shared types (mirror app/schemas.py) ---------------------------------------------
export type DigestFrequency = "weekly" | "monthly";
export type Visibility = "community" | "village";
export type ImageKind = "profile" | "tile";

export type Link = { label: string; url: string };
export type ProfileSource = { type: string; url: string; title: string | null };

export type User = {
  id: number;
  email: string;
  display_name: string | null;
  digest_frequency: DigestFrequency;
  digest_paused: boolean;
  onboarded: boolean;
  // profile artifacts
  bio: string | null;
  contact_email: string | null;
  contact_phone: string | null;
  profile_image_url: string | null;
  tile_image_url: string | null;
  visibility: Visibility;
  cities: string[];
  links: Link[];
  villages: string[];
};

export type PublicProfile = {
  id: number;
  display_name: string | null;
  bio: string | null;
  contact_email: string | null;
  profile_image_url: string | null;
  tile_image_url: string | null;
  cities: string[];
  links: Link[];
  platforms: string[];
  sources: ProfileSource[];
  is_subscribed: boolean;
};

export type VerifyResult = { session_token: string; user: User };

export type SourcePreview = {
  type: string;
  resolved_url: string | null;
  title: string | null;
  found_count: number;
  latest_title: string | null;
  latest_published_at: string | null;
};

export type Source = {
  id: number;
  type: string;
  input_url: string;
  resolved_feed_url: string | null;
  title: string | null;
  last_checked_at: string | null;
  last_success_at: string | null;
  created_at: string;
};

export type Subscription = {
  feeder_id: number;
  display_name: string | null;
  platforms: string[];
};

export type Discover = {
  user_id: number;
  display_name: string | null;
  platforms: string[];
  is_subscribed: boolean;
  profile_image_url: string | null;
  tile_image_url: string | null;
};

export type DigestItem = {
  title: string | null;
  url: string;
  excerpt: string | null;
  text: string | null;
  kind: "long" | "short";
  published_at: string;
};

export type DigestSource = {
  label: string;
  longs: DigestItem[];
  shorts: DigestItem[];
};

export type DigestFeeder = {
  feeder_id: number;
  display_name: string | null;
  sources: DigestSource[];
  selected: DigestItem; // representative item shown in the compact format
};

export type DigestPreview = {
  window_start: string;
  window_end: string;
  feeders: DigestFeeder[];
  quiet_feeders: string[]; // followed feeders with sources but nothing in the window
  compact: boolean; // one-line-per-feeder format (many active feeders)
};

export type MePatch = {
  display_name?: string;
  digest_frequency?: DigestFrequency;
  digest_paused?: boolean;
  bio?: string;
  contact_email?: string;
  contact_phone?: string;
  visibility?: Visibility;
  cities?: string[];
  links?: Link[];
};

// --- error type carried to the UI so pages can surface 400 / 422 inline ---------------
export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
    this.name = "ApiError";
  }
}

function tokenHeader(): Record<string, string> {
  const token = localStorage.getItem(TOKEN_KEY);
  return token ? { authorization: `Bearer ${token}` } : {};
}

async function errorMessage(res: Response): Promise<string> {
  try {
    const body = await res.json();
    const detail = (body as { detail?: unknown }).detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail)) {
      // FastAPI 422 validation shape: [{ msg, loc, ... }]
      return detail
        .map((d) => (d && typeof d === "object" && "msg" in d ? String((d as { msg: unknown }).msg) : String(d)))
        .join("; ");
    }
  } catch {
    /* non-JSON body */
  }
  return `Request failed (${res.status})`;
}

type RequestOpts = {
  method?: string;
  json?: unknown;
  // multipart body; the browser sets the content-type (with boundary) itself, so we
  // must NOT add a content-type header when this is present.
  form?: FormData;
};

async function request<T>(path: string, opts: RequestOpts = {}): Promise<T> {
  const { method = "GET", json, form } = opts;
  const res = await fetch(`${API_URL}${path}`, {
    method,
    headers: {
      ...(json !== undefined ? { "content-type": "application/json" } : {}),
      ...tokenHeader(),
    },
    body: form !== undefined ? form : json !== undefined ? JSON.stringify(json) : undefined,
  });

  if (res.status === 401) {
    // Global 401 handler: token is dead (expired / revoked) → clear + bounce to login.
    localStorage.removeItem(TOKEN_KEY);
    if (window.location.pathname !== "/login") window.location.assign("/login");
    throw new ApiError(401, "Session expired");
  }
  if (!res.ok) throw new ApiError(res.status, await errorMessage(res));
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export const api = {
  // --- public auth ---
  requestLink: (email: string) =>
    request<{ message: string }>("/auth/request-link", { method: "POST", json: { email } }),
  verify: (token: string) =>
    request<VerifyResult>("/auth/verify", { method: "POST", json: { token } }),
  logout: () => request<{ message: string }>("/auth/logout", { method: "POST" }),
  unsubscribe: (token: string) =>
    request<{ message: string }>(`/unsubscribe?token=${encodeURIComponent(token)}`, {
      method: "POST",
    }),

  // --- me ---
  getMe: () => request<User>("/me"),
  updateMe: (patch: MePatch) => request<User>("/me", { method: "PATCH", json: patch }),
  uploadImage: (kind: ImageKind, file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<User>(`/me/images/${kind}`, { method: "POST", form });
  },
  deleteImage: (kind: ImageKind) =>
    request<User>(`/me/images/${kind}`, { method: "DELETE" }),

  // --- public profile ---
  getProfile: (id: number) => request<PublicProfile>(`/users/${id}`),

  // --- sources ---
  previewSource: (url: string) =>
    request<SourcePreview>("/sources/preview", { method: "POST", json: { url } }),
  listSources: () => request<Source[]>("/sources"),
  addSource: (url: string) => request<Source>("/sources", { method: "POST", json: { url } }),
  deleteSource: (id: number) => request<void>(`/sources/${id}`, { method: "DELETE" }),

  // --- subscriptions ---
  subscribe: (feederId: number) =>
    request<Subscription>("/subscriptions", { method: "POST", json: { feeder_id: feederId } }),
  unsubscribeFeeder: (feederId: number) =>
    request<void>(`/subscriptions/${feederId}`, { method: "DELETE" }),
  listSubscriptions: () => request<Subscription[]>("/subscriptions"),

  // --- discover ---
  discover: (q: string) =>
    request<Discover[]>(`/discover?q=${encodeURIComponent(q)}`),

  // --- digest preview ---
  digestPreview: () => request<DigestPreview>("/me/digest/preview"),
};
