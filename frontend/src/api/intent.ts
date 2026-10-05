import type { QueryClient } from "@tanstack/react-query";
import { askAheadUrl } from "./client";
import { warmPath } from "./prefetch";
import { adminUserOptions, hrEmployeeOptions } from "./queries";
import type { MeResponse } from "./types";

/** How long what was asked ahead of a click is good for: a second pass of the pointer over the same link asks for nothing. */
const AHEAD_STALE_MS = 30_000;

const code = (raw: string | undefined) => encodeURIComponent(raw ?? "");

/** The addresses a page reads first, by the address it is at (`/app` taken off), for the person looking. */
type Reads = (match: RegExpMatchArray, me: MeResponse) => string[];

/**
 * The pages that open from a link inside another page, and what each reads first, so the ask is made when the pointer comes
 * to the link and not when it is pressed: the page is usually here by the time the click lands (`askAheadUrl` keeps the answer for
 * the page's own ask). Only a page that is safe to ask for ahead is listed: it writes nothing when it is read, and the one
 * pointing at it is allowed to open it (a refused ask is a row in the audit log). Left out on purpose, because reading them is an
 * act: a client (an identity row at every read), a mail thread or a conversation (they are marked as read), the attendance card
 * (it settles days) and an assignment (the person is shown it).
 */
const READS: [RegExp, Reads][] = [
  // The task: the translator's own page, or the one the operation, the team leader and the admin read.
  [/^\/tasks\/([A-Za-z0-9-]{1,40})$/, ([, task], me) => [me.user.role === "translator" && !me.user.is_admin ? `/api/v1/translator/tasks/${code(task)}/` : `/api/v1/tasks/${code(task)}/`]],
  [/^\/hr\/candidates\/([A-Za-z0-9-]{1,40})$/, ([, candidate]) => [`/api/v1/hr/candidates/${code(candidate)}/`]],
  [/^\/hr\/candidates\/([A-Za-z0-9-]{1,40})\/hire$/, ([, candidate]) => [`/api/v1/hr/candidates/${code(candidate)}/hire/`]],
  [/^\/hr\/attendance\/(\d{1,9})$/, ([, day]) => [`/api/v1/hr/attendance/${day}/`]],
  [/^\/hr\/vacancies\/([A-Za-z0-9-]{1,40})$/, ([, vacancy]) => [`/api/v1/hr/vacancies/${code(vacancy)}/`]],
  [/^\/hr\/interviews\/(\d{1,9})$/, ([, interview]) => [`/api/v1/hr/interviews/${interview}/`]],
  [/^\/accounts\/lines\/(\d{1,9})$/, ([, line]) => [`/api/v1/accounts/lines/${line}/`]],
  [/^\/accounts\/salary\/(\d{1,9})$/, ([, person]) => [`/api/v1/accounts/salary/${person}/`]],
  [/^\/reviewer\/tests\/(\d{1,9})$/, ([, test]) => [`/api/v1/reviewer/tests/${test}/`]],
  [/^\/hr\/employees\/new$/, (_match, me) => (me.user.is_admin ? ["/api/v1/admin/users/new/"] : [])],
];

/** The employee's file is asked through its query (the page and the account form are two answers, and the page reads both). */
const FILE = /^\/hr\/employees\/(\d{1,9})$/;

function askFile(client: QueryClient, id: number, me: MeResponse): Promise<unknown> {
  // The employee files are for who may recruit (HR and the admin); the admin's half is the admin's.
  if (!(me.user.is_admin || me.can.recruit)) return Promise.resolve();
  return Promise.all([
    client.prefetchQuery({ ...hrEmployeeOptions(id), staleTime: AHEAD_STALE_MS }),
    me.user.is_admin ? client.prefetchQuery({ ...adminUserOptions(id), staleTime: AHEAD_STALE_MS }) : Promise.resolve(),
  ]);
}

/**
 * Ask ahead for the page a link inside the app (`/app/...`) opens: a page of the menu (warmed the way the background warm-up
 * does it), the employee's file, or one of the detail pages above. Any other address is left to open as it does.
 */
export async function askAhead(client: QueryClient, pathname: string, me: MeResponse): Promise<void> {
  if (!pathname.startsWith("/app/") && pathname !== "/app") return;
  const inside = pathname.slice("/app".length).replace(/\/$/, "") || "/";
  try {
    const file = inside.match(FILE);
    if (file) {
      await askFile(client, Number(file[1]), me);
      return;
    }
    for (const [pattern, reads] of READS) {
      const match = inside.match(pattern);
      if (!match) continue;
      await Promise.all(reads(match, me).map((url) => askAheadUrl(url)));
      return;
    }
    // A page of the menu itself (a link in the sidebar, or one that opens the same page): the way it is warmed in the background.
    await warmPath(client, inside, me);
  } catch {
    // An ask that fails is a page that opens as it did before.
  }
}
