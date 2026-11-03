import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ApiError, api } from "./client";
import { qk } from "./keys";
import type { AiReviewDetail, AiReviewLabel } from "./types";

/** A line to the AI: words and/or files (each with what the leader says it is). `session` goes on in one; left out, a new one opens. */
export interface AiReviewInput {
  session: number | null;
  text: string;
  files: { file: File; label: AiReviewLabel }[];
}

const url = (id: number) => `/api/v1/ai-review/${id}/`;

/** «ابعت»: the files go in one request and the answer comes later (`api_docreview.send`). The reply is the session, so a new one is found at once. */
export function useAiReviewSend() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (input: AiReviewInput) => {
      const form = new FormData();
      if (input.session !== null) form.append("session", String(input.session));
      form.append("text", input.text);
      for (const { file, label } of input.files) {
        form.append("files", file, file.name);
        form.append("labels", label);
      }
      const answer = await api<AiReviewDetail | { ok: false }>("/api/v1/ai-review/send/", { multipart: form });
      if (!answer.ok) throw new ApiError(200, "refused", answer);
      return answer;
    },
    onSuccess: (answer) => client.setQueryData(qk.aiReviewSession(answer.session.id), answer),
    onSettled: () => void client.invalidateQueries({ queryKey: qk.aiReview }),
  });
}

/** «جرّب تاني»: ask again for the answer that failed, with the files the server kept. */
export function useAiReviewRetry() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => api<AiReviewDetail>(`${url(id)}retry/`, { form: {} }),
    onSuccess: (answer) => client.setQueryData(qk.aiReviewSession(answer.session.id), answer),
    onSettled: () => void client.invalidateQueries({ queryKey: qk.aiReview }),
  });
}

/** Delete a session with its talk and files. The server refuses (409) while the AI is still answering in it. */
export function useAiReviewDelete() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => api<{ ok: boolean }>(`${url(id)}delete/`, { form: {} }),
    onSettled: () => void client.invalidateQueries({ queryKey: qk.aiReview }),
  });
}
