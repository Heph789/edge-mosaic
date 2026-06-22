// TanStack Query hooks — server state for the authed app. Query keys are stable so
// mutations can target them for optimistic updates / invalidation.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type Discover, type ImageKind, type MePatch, type User } from "../api";

const keys = {
  sources: ["sources"] as const,
  subscriptions: ["subscriptions"] as const,
  digestPreview: ["digest-preview"] as const,
  discover: (q: string) => ["discover", q] as const,
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

// Discover. Empty query browses the whole directory (the API lists all, capped); a term
// filters by name. Always enabled so the Directory shows a list by default.
export function useDiscover(q: string) {
  const term = q.trim();
  return useQuery({
    queryKey: keys.discover(term),
    queryFn: () => api.discover(term),
  });
}

// --- me mutation ----------------------------------------------------------------------
export function useUpdateMe(onUser?: (user: User) => void) {
  return useMutation({
    mutationFn: (patch: MePatch) => api.updateMe(patch),
    onSuccess: (user) => onUser?.(user),
  });
}

// Image upload / removal. Both return the fresh User so the caller can sync auth context.
export function useUploadImage(onUser?: (user: User) => void) {
  return useMutation({
    mutationFn: ({ kind, file }: { kind: ImageKind; file: File }) =>
      api.uploadImage(kind, file),
    onSuccess: (user) => onUser?.(user),
  });
}

export function useDeleteImage(onUser?: (user: User) => void) {
  return useMutation({
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
    mutationFn: async ({ feederId, subscribe }: { feederId: number; subscribe: boolean }) => {
      if (subscribe) await api.subscribe(feederId);
      else await api.unsubscribeFeeder(feederId);
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["profile", username] });
      qc.invalidateQueries({ queryKey: keys.subscriptions });
      qc.invalidateQueries({ queryKey: ["discover"] });
      qc.invalidateQueries({ queryKey: keys.digestPreview });
    },
  });
}

// --- sources mutations ----------------------------------------------------------------
export function useAddSource() {
  const qc = useQueryClient();
  return useMutation({
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
    mutationFn: (feederId: number) => api.unsubscribeFeeder(feederId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: keys.subscriptions });
      qc.invalidateQueries({ queryKey: keys.digestPreview });
      // Any cached discover results may now show this feeder as unsubscribed.
      qc.invalidateQueries({ queryKey: ["discover"] });
    },
  });
}
