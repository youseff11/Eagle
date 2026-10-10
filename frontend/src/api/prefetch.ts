import type { QueryClient } from "@tanstack/react-query";
import { askAheadUrl } from "./client";
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
 * The other pages of the menu, by the address each one reads first (what it asks with nothing chosen yet). Not through a query's
 * own key: the answer waits by address (`askAheadUrl`) for the page that asks for it, so a page needs no registering to be warm.
 * The same rules as `WARM`: only reads that write nothing, and only for a person whose menu has the page. Left out on purpose:
 * the client records and the client codes (an identity row at every read) and the attendance card (it settles days when read).
 */
export const WARM_URLS: Record<string, readonly string[]> = {
  "/admin/settings": ["/api/v1/admin/settings/"],
  "/admin/simulate": ["/api/v1/admin/simulate/"],
  "/admin/audit": ["/api/v1/admin/audit/"],
  "/admin/reset-mail": ["/api/v1/admin/reset/mail/"],
  "/admin/reset-tasks": ["/api/v1/admin/reset/tasks/"],
  "/admin/reset-staff": ["/api/v1/admin/reset/staff/"],
  "/accounts": ["/api/v1/accounts/overview/"],
  "/accounts/attendance": ["/api/v1/accounts/attendance/"],
  "/accounts/violations": ["/api/v1/accounts/violations/"],
  "/accounts/rules": ["/api/v1/accounts/rules/"],
  "/hr/recruitment": ["/api/v1/hr/recruitment/"],
  "/hr/vacancies": ["/api/v1/hr/vacancies/"],
  "/hr/candidates": ["/api/v1/hr/candidates/"],
  "/hr/questions": ["/api/v1/hr/questions/"],
  "/hr/recruitment/settings": ["/api/v1/hr/recruitment/settings/"],
  "/hr/approvals": ["/api/v1/hr/approvals/"],
  "/reviewer/tests": ["/api/v1/reviewer/tests/"],
  "/hr/attendance": ["/api/v1/hr/attendance/"],
  "/hr/schedules": ["/api/v1/hr/schedules/"],
  "/hr/shifts": ["/api/v1/hr/shifts/"],
  "/hr/leave": ["/api/v1/hr/leave/"],
  "/hr/overtime": ["/api/v1/hr/overtime/"],
  "/hr/report": ["/api/v1/hr/report/"],
  "/hr/probation": ["/api/v1/hr/probation/"],
  "/hr/performance": ["/api/v1/hr/performance/board/"],
  "/hr/complaints": ["/api/v1/hr/complaints/"],
  "/hr/salary-requests": ["/api/v1/hr/salary-requests/"],
  "/hr/salary-plans": ["/api/v1/hr/salary-plans/"],
  "/hr/offices": ["/api/v1/hr/offices/"],
  "/hr/devices": ["/api/v1/hr/devices/"],
  "/payroll": ["/api/v1/translator/payroll/"],
  "/line": ["/api/v1/sales/line/"],
  "/leads": ["/api/v1/b2b/sheets/"],
  "/sales-performance": ["/api/v1/b2b/kpis/"],
  "/leave": ["/api/v1/leave/"],
};

/** Warm one menu address, by whichever way it is listed; an address in neither list is left to open cold. */
export async function warmPath(client: QueryClient, path: string, me: MeResponse): Promise<void> {
  if (Object.hasOwn(WARM, path)) {
    await WARM[path]!(client, me);
  } else if (Object.hasOwn(WARM_URLS, path)) {
    await Promise.all(WARM_URLS[path]!.map((url) => askAheadUrl(url)));
  }
}

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
    if (!Object.hasOwn(WARM, path) && !Object.hasOwn(WARM_URLS, path)) continue;
    if (stopped()) return;
    try {
      await warmPath(client, path, me);
    } catch {
      // A warm-up that fails is a page that opens cold, as before.
    }
  }
}
