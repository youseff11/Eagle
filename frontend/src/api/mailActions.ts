import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ApiError, api } from "./client";
import { qk } from "./keys";
import type { MailSeenResponse } from "./types";

/**
 * What is done in the mailbox: the classic endpoints, unchanged (`api.mail_reply`, `api.fetch_mail`) and the one
 * door that was missing (the conversation was read - the classic page did it by being opened, a GET).
 *
 * Whatever the answer, the mailbox is asked again afterwards: a reply moves its conversation to the top of the
 * list, and fetching brings letters in.
 */
function useMailRefresh() {
  const client = useQueryClient();
  return () => {
    void client.invalidateQueries({ queryKey: qk.mailLists });
    void client.invalidateQueries({ queryKey: qk.me });
  };
}

/** «جيب الميلات دلوقتي»: poll the mailbox now instead of waiting for the scheduled run. */
export function useFetchMail() {
  const refresh = useMailRefresh();
  return useMutation({
    mutationFn: () => api<{ ok: boolean; created: number; error: string }>("/api/mail/fetch/", { form: {} }),
    onSettled: refresh,
  });
}

/** What a reply answered: it is there either way - a failed one stays on the page, marked, with the reason. */
export interface Replied {
  ok: boolean;
  id?: number;
  error: string;
}

/** Answer a conversation by e-mail: text, files, or both. `ApiError.payload.error` says why it did not go. */
export function useReply(id: number) {
  const client = useQueryClient();
  const refresh = useMailRefresh();
  return useMutation({
    mutationFn: ({ body, files }: { body: string; files: File[] }) => {
      const form = new FormData();
      form.append("body", body);
      for (const file of files) form.append("files", file);
      return api<Replied>(`/api/inbox/thread/${id}/reply/`, { multipart: form });
    },
    onSettled: () => {
      void client.invalidateQueries({ queryKey: qk.mailThread(id) });
      refresh();
    },
  });
}

/** «استلمت»: the client is told it arrived and the letter is claimed. A letter already claimed is refused. */
export function useConfirmReceipt(thread: number) {
  const client = useQueryClient();
  const refresh = useMailRefresh();
  return useMutation({
    mutationFn: async (message: number) => {
      const answer = await api<{ ok: boolean; error?: string; claimed_by?: string }>(`/api/v1/messages/${message}/confirm/`, { form: {} });
      if (!answer.ok) throw new ApiError(200, "refused", answer);
      return answer;
    },
    onSettled: () => {
      void client.invalidateQueries({ queryKey: qk.mailThread(thread) });
      refresh();
    },
  });
}

/** The page has shown the letters: they are read, and the badge falls. Nothing on the page changes by it. */
export function useMarkThreadSeen(id: number) {
  const refresh = useMailRefresh();
  return useMutation({
    mutationFn: () => api<MailSeenResponse>(`/api/v1/mail/threads/${id}/seen/`, { form: {} }),
    onSuccess: refresh,
  });
}
