import { QueryClient } from "@tanstack/react-query";
import { afterEach, describe, expect, it, vi } from "vitest";
import { jsonResponse, me, mockFetch } from "../test/helpers";
import { askAhead } from "./intent";

afterEach(() => vi.unstubAllGlobals());

function serve() {
  const mocked = mockFetch({ "/api/v1/": () => jsonResponse({ ok: true }) });
  vi.stubGlobal("fetch", mocked.fn);
  return mocked.calls;
}

const client = () => new QueryClient({ defaultOptions: { queries: { retry: false } } });
const asked = (calls: { url: string }[]) => calls.map((call) => call.url).sort();

describe("askAhead: a link a pointer comes to", () => {
  it("asks for an employee's file, and for the admin's half of it too when the person is the admin", async () => {
    const calls = serve();
    await askAhead(client(), "/app/hr/employees/7", me({ role: "admin", is_admin: true }));
    expect(asked(calls)).toEqual(["/api/v1/admin/users/7/", "/api/v1/hr/employees/7/"]);
  });

  it("asks for the file alone for HR, and for nothing at all for somebody who may not open it (a refusal is a row in the log)", async () => {
    const calls = serve();
    await askAhead(client(), "/app/hr/employees/7", me({ role: "hr" }));
    expect(asked(calls)).toEqual(["/api/v1/hr/employees/7/"]);
    calls.length = 0;
    await askAhead(client(), "/app/hr/employees/7", { ...me({ role: "operation" }), can: { manage_attendance: false, recruit: false, review_tests: false, approve_hiring: false } });
    expect(calls).toEqual([]);
  });

  it("asks for a task through the page the person's role opens", async () => {
    const calls = serve();
    await askAhead(client(), "/app/tasks/TSK-00012", me({ role: "translator" }));
    await askAhead(client(), "/app/tasks/TSK-00013", me({ role: "operation" }));
    await askAhead(client(), "/app/tasks/TSK-00014", me({ role: "admin", is_admin: true }));
    expect(asked(calls)).toEqual(["/api/v1/tasks/TSK-00013/", "/api/v1/tasks/TSK-00014/", "/api/v1/translator/tasks/TSK-00012/"]);
  });

  it("asks for the detail pages that are safe to read ahead", async () => {
    const calls = serve();
    const person = me({ role: "admin", is_admin: true });
    for (const path of ["/app/hr/candidates/CAN-0001", "/app/hr/candidates/CAN-0001/hire", "/app/hr/attendance/5", "/app/hr/vacancies/VAC-0002", "/app/hr/interviews/4", "/app/accounts/lines/9", "/app/accounts/salary/3", "/app/reviewer/tests/8", "/app/hr/employees/new"]) {
      await askAhead(client(), path, person);
    }
    expect(asked(calls)).toEqual([
      "/api/v1/accounts/lines/9/",
      "/api/v1/accounts/salary/3/",
      "/api/v1/admin/users/new/",
      "/api/v1/hr/attendance/5/",
      "/api/v1/hr/candidates/CAN-0001/",
      "/api/v1/hr/candidates/CAN-0001/hire/",
      "/api/v1/hr/interviews/4/",
      "/api/v1/hr/vacancies/VAC-0002/",
      "/api/v1/reviewer/tests/8/",
    ]);
  });

  it("asks for a page of the menu the way the warm-up does", async () => {
    const calls = serve();
    await askAhead(client(), "/app/hr/leave", me({ role: "hr" }));
    await askAhead(client(), "/app/tasks", me({ role: "operation" }));
    expect(asked(calls)).toEqual(["/api/v1/hr/leave/", "/api/v1/tasks/"]);
  });

  it("never asks ahead for what reading would do something: a client, a mail thread, a conversation, the attendance card, an assignment", async () => {
    const calls = serve();
    const person = me({ role: "admin", is_admin: true });
    for (const path of ["/app/clients", "/app/clients/CL-0001", "/app/admin/clients", "/app/admin/clients/CL-0001/edit", "/app/inbox/thread/5", "/app/chats/CL-0001", "/app/attendance", "/app/assignments/4"]) {
      await askAhead(client(), path, person);
    }
    expect(calls).toEqual([]);
  });

  it("leaves an address outside the app, or one it does not know, alone", async () => {
    const calls = serve();
    const person = me({ role: "admin", is_admin: true });
    for (const path of ["/privacy/", "/files/avatars/x.jpg", "/app/something/odd", "/app/tasks/../etc", "/app/hr/employees/abc", "/app/hr/employees/12345678901"]) {
      await askAhead(client(), path, person);
    }
    expect(calls).toEqual([]);
  });
});
