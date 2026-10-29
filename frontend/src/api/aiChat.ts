import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "./client";
import { qk } from "./keys";
import type { AiChatResponse } from "./types";

const url = (code: string) => `/api/v1/tasks/${encodeURIComponent(code)}/ai-chat/`;

/** How often the talk is asked again while the AI is still writing its answer. */
const WRITING_MS = 2500;

/** The team leader's talk with the AI on a task. Asked again, quickly, only while an answer is being written. */
export function useAiChat(code: string, enabled: boolean) {
  return useQuery({
    queryKey: qk.aiChat(code),
    queryFn: () => api<AiChatResponse>(url(code)),
    enabled,
    refetchInterval: (query) => (query.state.data?.pending ? WRITING_MS : false),
  });
}

/** A line to the AI: words and/or one file. The answer to it comes later, in the talk. */
export function useSendAiChat(code: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ text, file }: { text: string; file?: File | null }) => {
      const body = new FormData();
      body.append("text", text);
      if (file) body.append("file", file, file.name);
      return api<AiChatResponse>(`${url(code)}send/`, { multipart: body });
    },
    onSuccess: (answer) => client.setQueryData(qk.aiChat(code), answer),
    onSettled: () => void client.invalidateQueries({ queryKey: qk.aiChat(code) }),
  });
}
