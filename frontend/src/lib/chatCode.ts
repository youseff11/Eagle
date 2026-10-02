import type { ChatKind } from "../api/types";

/** Which list a conversation belongs to, from the code its row carries (`g12` a group, `u5` a colleague, a client code otherwise). */
export function kindOfCode(code: string): ChatKind {
  if (/^g\d+$/.test(code)) return "groups";
  if (/^u\d+$/.test(code)) return "staff";
  return "clients";
}
