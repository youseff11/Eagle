import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "./client";
import { qk } from "./keys";
import type { MeResponse } from "./types";

/** What both doors answer: the picture's address now, or null when there is none. */
interface AvatarAnswer {
  ok: true;
  avatar: string | null;
}

/** The person's own picture, in `/me/`: said at once from the answer, and asked for again to be sure. */
function useAvatarWrite<V>(run: (value: V) => Promise<AvatarAnswer>) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: run,
    onSuccess: ({ avatar }) =>
      client.setQueryData<MeResponse>(qk.me, (me) => (me ? { ...me, user: { ...me.user, avatar } } : me)),
    onSettled: () => void client.invalidateQueries({ queryKey: qk.me }),
  });
}

/** Put a picture there (the square the page cut), instead of the one there. */
export function useSetAvatar() {
  return useAvatarWrite<File>((file) => {
    const body = new FormData();
    body.append("file", file);
    return api<AvatarAnswer>("/api/v1/me/avatar/", { multipart: body });
  });
}

/** What a person types to change their own password: the one they have, and the new one twice. */
export interface PasswordChange {
  old_password: string;
  new_password1: string;
  new_password2: string;
}

/**
 * Change the signed-in person's own password. It rides in this request and in nothing else: the page empties its boxes and
 * `reset()`s the mutation once the answer is in, so no copy is kept in the cache's state.
 */
export function useChangePassword() {
  return useMutation({
    mutationFn: (values: PasswordChange) => api<{ ok: true }>("/api/v1/me/password/", { json: values }),
  });
}

/** Take the picture off: the initials are drawn again. */
export function useRemoveAvatar() {
  return useAvatarWrite<void>(() => api<AvatarAnswer>("/api/v1/me/avatar/remove/", { json: {} }));
}
