import type { ThreadEntry } from "../api/types";

/**
 * The client's new documents that arrived together with `entry`: the messages around it, one right after the other with
 * nothing of anybody's in between, from the same day, each with a document and none of them already behind a task. WhatsApp
 * delivers every file of an album as a message of its own, so turning one of them into a task would take one file; this is
 * the whole album. A message that is already a task (the «طلب جديد» button) is its own run: it is not mixed with new ones.
 */
export function newFilesRun(messages: ThreadEntry[], entry: ThreadEntry): ThreadEntry[] {
  const eligible = (one: ThreadEntry) => one.kind === "in" && one.actions && one.has_docs && !one.has_task && one.date === entry.date;
  const at = messages.findIndex((one) => one.uid === entry.uid);
  if (at < 0 || !eligible(entry)) return [entry];
  let from = at;
  while (from > 0 && eligible(messages[from - 1]!)) from -= 1;
  let to = at;
  while (to < messages.length - 1 && eligible(messages[to + 1]!)) to += 1;
  return messages.slice(from, to + 1);
}
