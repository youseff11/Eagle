import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";

/**
 * The classic interface's own `post()` (static/js/app.js), run as the browser runs it.
 *
 * Not part of the new app, but the new app sends people there to accept an assignment, and
 * daphne answers a POST whose body is an empty multipart form with a bare 400 before Django
 * sees it. The classic scripts build their form data with `new FormData()`, so a call with
 * nothing to send (accept, decline-less actions) became exactly that request, and
 * "accept" answered "too late" under daphne although it worked under the old host.
 */
type Post = (url: string, data?: Record<string, string> | FormData) => Promise<unknown>;

let post: Post;

beforeAll(() => {
  const source = readFileSync(resolve(import.meta.dirname, "../../../static/js/app.js"), "utf-8");
  new Function(source)();
  post = (window as unknown as { Eagle: { post: Post } }).Eagle.post;
});

afterEach(() => vi.unstubAllGlobals());

function lastRequest() {
  const fetchMock = vi.fn(async (_url: string, _init?: RequestInit) => new Response(JSON.stringify({ ok: true })));
  vi.stubGlobal("fetch", fetchMock);
  document.cookie = "csrftoken=token123";
  return {
    send: async (data?: Record<string, string> | FormData) => {
      await post("/api/assignments/3/accept/", data);
      return fetchMock.mock.calls[0]![1] as RequestInit;
    },
  };
}

describe("the classic post()", () => {
  it("sends no body at all when there is nothing to send", async () => {
    const init = await lastRequest().send({});
    expect(init.method).toBe("POST");
    expect(init.body).toBeUndefined();
  });

  it("does the same for an empty form that was passed in", async () => {
    const init = await lastRequest().send(new FormData());
    expect(init.body).toBeUndefined();
  });

  it("does the same when nothing is passed", async () => {
    const init = await lastRequest().send(undefined);
    expect(init.body).toBeUndefined();
  });

  it("still sends the fields it was given", async () => {
    const init = await lastRequest().send({ reason: "busy" });
    expect(init.body).toBeInstanceOf(FormData);
    expect((init.body as FormData).get("reason")).toBe("busy");
  });

  it("still sends a form that has something in it", async () => {
    const form = new FormData();
    form.append("body", "hello");
    const init = await lastRequest().send(form);
    expect((init.body as FormData).get("body")).toBe("hello");
  });

  it("always carries the CSRF token and says it is an XHR", async () => {
    const init = await lastRequest().send({});
    expect(init.headers).toMatchObject({ "X-CSRFToken": "token123", "X-Requested-With": "XMLHttpRequest" });
  });
});
