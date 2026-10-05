import type { QueryClient } from "@tanstack/react-query";
import {
  adminOverviewOptions,
  chatListOptions,
  hrRegisterOptions,
  leadBoardOptions,
  leadHomeOptions,
  mailThreadsOptions,
  notificationsOptions,
  tasksOptions,
  teamOptions,
  translatorHomeOptions,
} from "./queries";
import type { ChatKind, MeResponse } from "./types";

type Warm = (client: QueryClient, me: MeResponse) => Promise<unknown>;

const CHAT_KINDS = ["clients", "groups", "staff"];

/**
 * What to ask for, before the click, for the pages a person opens most. A page opened on data that is already here
 * draws at once; one that has to ask first shows a loading screen, once per page per visit.
 *
 * The first page of each, with the arguments the page itself starts from (the same options its hook uses, so the same
 * key). Only addresses that are safe to ask for ahead of time are listed, and each address is warmed only when it is
 * in the person's own menu:
 *  - a refused request is written to the audit log, so nobody warms a page they may not open;
 *  - the client records and the client codes write an identity row at every GET, so they are never warmed;
 *  - the attendance card settles forgotten days when it is read, so it is left until its owner opens it.
 */
export const WARM: Record<string, Warm> = {
  "/notifications": (client) => client.prefetchInfiniteQuery(notificationsOptions()),
  "/translator": (client) => client.prefetchQuery(translatorHomeOptions()),
  "/tasks": (client) => client.prefetchQuery(tasksOptions("")),
  "/team": (client) => client.prefetchQuery(teamOptions()),
  "/inbox": (client) => client.prefetchQuery(mailThreadsOptions("", "")),
  "/lead": (client) => client.prefetchQuery(leadHomeOptions()),
  "/lead/translators": (client) => client.prefetchQuery(leadBoardOptions()),
  "/admin": (client) => client.prefetchQuery(adminOverviewOptions()),
  "/hr/employees": (client) => client.prefetchQuery(hrRegisterOptions("")),
  "/chats": (client, me) => {
    // The list the chats page opens on: the first of the person's own kinds.
    const kind = me.chats.types.find((type) => CHAT_KINDS.includes(type)) as ChatKind | undefined;
    return kind ? client.prefetchQuery(chatListOptions(kind, "")) : Promise.resolve();
  },
};

/**
 * Warm these addresses one after the other (not all at once: the page the person is on comes first). `stopped` is
 * asked before each, so a person who has gone or whose menu changed stops it.
 */
export async function warmPages(
  client: QueryClient,
  paths: readonly string[],
  me: MeResponse,
  stopped: () => boolean = () => false,
): Promise<void> {
  for (const path of paths) {
    const warm = Object.hasOwn(WARM, path) ? WARM[path] : undefined;
    if (!warm) continue;
    if (stopped()) return;
    try {
      await warm(client, me);
    } catch {
      // A warm-up that fails is a page that opens cold, as before.
    }
  }
}
