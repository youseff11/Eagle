import type { ChatKind } from "../api/types";

/** Which list a conversation belongs to, from the code its row carries (`g12` a group, `u5` a colleague, a client code otherwise). */
export function kindOfCode(code: string): ChatKind {
  if (/^g\d+$/.test(code)) return "groups";
  if (/^u\d+$/.test(code)) return "staff";
  return "clients";
}

/** Where the AI's notes for a leader's chat are asked for: a work group or a colleague's chat; a client's conversation has none. */
export function aiNotesPath(code: string): string | null {
  const group = /^g(\d+)$/.exec(code)?.[1];
  if (group) return `/api/v1/groups/${group}/ai-notes/`;
  const person = /^u(\d+)$/.exec(code)?.[1];
  return person ? `/api/v1/staff/${person}/ai-notes/` : null;
}
