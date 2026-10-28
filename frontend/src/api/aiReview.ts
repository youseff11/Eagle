import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ApiError, api } from "./client";
import { qk } from "./keys";

/** What the leader hands the AI: the files of each side and, in words, the languages and what to look at (all of these optional). */
export interface AiReviewInput {
  source: File[];
  target: File[];
  sourceLang: string;
  targetLang: string;
  instructions: string;
}

/** «ابعت للـAI»: the files go in one request and the notes come later (`api_docreview.send`). A refusal arrives as its own sentence. */
export function useAiReviewSend() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (input: AiReviewInput) => {
      const form = new FormData();
      for (const file of input.source) form.append("source", file, file.name);
      for (const file of input.target) form.append("target", file, file.name);
      form.append("source_lang", input.sourceLang);
      form.append("target_lang", input.targetLang);
      form.append("instructions", input.instructions);
      const answer = await api<{ ok: boolean; id: number }>("/api/v1/ai-review/send/", { multipart: form });
      if (!answer.ok) throw new ApiError(200, "refused", answer);
      return answer;
    },
    onSettled: () => void client.invalidateQueries({ queryKey: qk.aiReview }),
  });
}

/** Take a finished check off the page. */
export function useAiReviewDelete() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => api<{ ok: boolean }>(`/api/v1/ai-review/${id}/delete/`, { form: {} }),
    onSettled: () => void client.invalidateQueries({ queryKey: qk.aiReview }),
  });
}
