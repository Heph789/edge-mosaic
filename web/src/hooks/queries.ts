// TanStack Query hooks — server state for the authed app. Query keys are stable so
// mutations can target them for optimistic updates / invalidation.
import {
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
  type InfiniteData,
} from "@tanstack/react-query";
import { api, type Discover, type ImageKind, type MePatch, type User } from "../api";

// Mirrors DISCOVER_PAGE_SIZE in api/app/routers/discover.py — a full page implies there
// may be more, so we ask for the next one.
const DISCOVER_PAGE_SIZE = 24;

const keys = {
  sources: ["sources"] as const,
  subscriptions: ["subscriptions"] as const,
  digestPreview: ["digest-preview"] as const,
  discover: (q: string) => ["discover", q] as const,
  discoverAll: ["discover-all"] as const,
};

// --- queries --------------------------------------------------------------------------
export function useSources() {
  return useQuery({ queryKey: keys.sources, queryFn: api.listSources });
}

export function useSubscriptions() {
  return useQuery({ queryKey: keys.subscriptions, queryFn: api.listSubscriptions });
}

export function useDigestPreview() {
  return useQuery({ queryKey: keys.digestPreview, queryFn: api.digestPreview });
}

// Discover. Empty query browses the whole directory; a term filters by name. Paginated for
// infinite scroll: each page is a full list slice, fetched by offset. A short final page
// (fewer than DISCOVER_PAGE_SIZE rows) signals the end. Always enabled so the Directory
// shows a list by default.
export function useDiscover(q: string) {
  const term = q.trim();
  return useInfiniteQuery({
    queryKey: keys.discover(term),
    queryFn: ({ pageParam }) => api.discover(term, pageParam),
    initialPageParam: 0,
    getNextPageParam: (lastPage, allPages) =>
      lastPage.length === DISCOVER_PAGE_SIZE
        ? allPages.length * DISCOVER_PAGE_SIZE
        : undefined,
  });
}

// Load the WHOLE directory in one shot for the mosaic (and client-side list filtering).
// The mosaic lays everyone out at once, so we page through /discover to exhaustion rather
// than lazy-loading. Fine at the current scale (mid-hundreds); revisit if it grows.
export function useAllDiscover() {
  return useQuery({
    queryKey: keys.discoverAll,
    queryFn: async () => {
      const all: Discover[] = [];
      let offset = 0;
      // Guard against an unbounded loop if the API ever misbehaves.
      for (let guard = 0; guard < 200; guard++) {
        const page = await api.discover("", offset);
        all.push(...page);
        if (page.length < DISCOVER_PAGE_SIZE) break;
        offset += DISCOVER_PAGE_SIZE;
      }
      return all;
    },
  });
}

// Optimistic subscribe toggle against the flat ["discover-all"] cache the mosaic/list read.
export function useToggleSubscribeAll() {
  const qc = useQueryClient();
  const key = keys.discoverAll;
  return useMutation({
    meta: { operation: "toggleSubscribe" },
    mutationFn: async ({ userId, subscribe }: { userId: number; subscribe: boolean }) => {
      if (subscribe) await api.subscribe(userId);
      else await api.unsubscribeFeeder(userId);
    },
    onMutate: async ({ userId, subscribe }) => {
      await qc.cancelQueries({ queryKey: key });
      const prev = qc.getQueryData<Discover[]>(key);
      qc.setQueryData<Discover[]>(key, (old) =>
        old?.map((d) => (d.user_id === userId ? { ...d, is_subscribed: subscribe } : d))
      );
      return { prev };
    },
    onError: (_err, _vars, ctx) => {
      if (ctx?.prev) qc.setQueryData(key, ctx.prev);
    },
    onSettled: () => {
      // The optimistic patch above already holds the correct is_subscribed, so we skip
      // re-invalidating (and thus refetching) the whole directory — that full-list refetch
      // re-rendered every row. Only the derived subscription/digest views need revalidating.
      qc.invalidateQueries({ queryKey: keys.subscriptions });
      qc.invalidateQueries({ queryKey: keys.digestPreview });
    },
  });
}

// --- me mutation ----------------------------------------------------------------------
export function useUpdateMe(onUser?: (user: User) => void) {
  return useMutation({
    meta: { operation: "updateMe" },
    mutationFn: (patch: MePatch) => api.updateMe(patch),
    onSuccess: (user) => onUser?.(user),
  });
}

// Image upload / removal. Both return the fresh User so the caller can sync auth context.
export function useUploadImage(onUser?: (user: User) => void) {
  return useMutation({
    meta: { operation: "uploadImage" },
    mutationFn: ({ kind, file }: { kind: ImageKind; file: File }) =>
      api.uploadImage(kind, file),
    onSuccess: (user) => onUser?.(user),
  });
}

export function useDeleteImage(onUser?: (user: User) => void) {
  return useMutation({
    meta: { operation: "deleteImage" },
    mutationFn: (kind: ImageKind) => api.deleteImage(kind),
    onSuccess: (user) => onUser?.(user),
  });
}

// --- public profile -------------------------------------------------------------------
export function useProfile(username: string | null) {
  return useQuery({
    queryKey: ["profile", username] as const,
    queryFn: () => api.getProfileByUsername(username as string),
    enabled: username != null,
  });
}

// Follow toggle for the standalone /p/{username} page. Unlike useToggleSubscribe (which is
// wired to the discover-list cache), this just re-fetches the profile after the change.
export function useToggleFollowProfile(username: string) {
  const qc = useQueryClient();
  return useMutation({
    meta: { operation: "toggleFollowProfile" },
    mutationFn: async ({ feederId, subscribe }: { feederId: number; subscribe: boolean }) => {
      if (subscribe) await api.subscribe(feederId);
      else await api.unsubscribeFeeder(feederId);
    },
    onSuccess: (_data, { feederId, subscribe }) => {
      qc.invalidateQueries({ queryKey: ["profile", username] });
      qc.invalidateQueries({ queryKey: keys.subscriptions });
      qc.invalidateQueries({ queryKey: keys.digestPreview });
      // Patch the directory cache in place rather than invalidating it — refetching the
      // whole ["discover-all"] list to reflect one toggle re-rendered every tile/row.
      qc.setQueryData<Discover[]>(keys.discoverAll, (old) =>
        old?.map((d) => (d.user_id === feederId ? { ...d, is_subscribed: subscribe } : d))
      );
    },
  });
}

// --- sources mutations ----------------------------------------------------------------
export function useAddSource() {
  const qc = useQueryClient();
  return useMutation({
    meta: { operation: "addSource" },
    mutationFn: (url: string) => api.addSource(url),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: keys.sources });
      // A new source can change a feeder's platforms / digest contents.
      qc.invalidateQueries({ queryKey: keys.digestPreview });
    },
  });
}

export function useDeleteSource() {
  const qc = useQueryClient();
  return useMutation({
    meta: { operation: "deleteSource" },
    mutationFn: (id: number) => api.deleteSource(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: keys.sources });
      qc.invalidateQueries({ queryKey: keys.digestPreview });
    },
  });
}

// --- subscription mutations -----------------------------------------------------------
// Optimistic toggle used by the Directory: flip is_subscribed in the ["discover", q]
// cache immediately, roll back on error, then revalidate discover + digest on settle.
export function useToggleSubscribe(q: string) {
  const qc = useQueryClient();
  const key = keys.discover(q.trim());
  return useMutation({
    meta: { operation: "toggleSubscribe" },
    mutationFn: async ({ userId, subscribe }: { userId: number; subscribe: boolean }) => {
      if (subscribe) await api.subscribe(userId);
      else await api.unsubscribeFeeder(userId);
    },
    onMutate: async ({ userId, subscribe }) => {
      await qc.cancelQueries({ queryKey: key });
      const prev = qc.getQueryData<InfiniteData<Discover[]>>(key);
      // Flip is_subscribed across every loaded page of the infinite-query cache.
      qc.setQueryData<InfiniteData<Discover[]>>(key, (old) =>
        old
          ? {
              ...old,
              pages: old.pages.map((page) =>
                page.map((d) =>
                  d.user_id === userId ? { ...d, is_subscribed: subscribe } : d
                )
              ),
            }
          : old
      );
      return { prev };
    },
    onError: (_err, _vars, ctx) => {
      if (ctx?.prev) qc.setQueryData(key, ctx.prev);
    },
    onSettled: () => {
      qc.invalidateQueries({ queryKey: key });
      qc.invalidateQueries({ queryKey: keys.subscriptions });
      qc.invalidateQueries({ queryKey: keys.digestPreview });
    },
  });
}

// Unsubscribe from the Digest tab's subscription list (no discover cache to flip).
export function useUnsubscribeFeeder() {
  const qc = useQueryClient();
  return useMutation({
    meta: { operation: "unsubscribeFeeder" },
    mutationFn: (feederId: number) => api.unsubscribeFeeder(feederId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: keys.subscriptions });
      qc.invalidateQueries({ queryKey: keys.digestPreview });
      // Any cached discover results may now show this feeder as unsubscribed.
      qc.invalidateQueries({ queryKey: ["discover"] });
    },
  });
}
