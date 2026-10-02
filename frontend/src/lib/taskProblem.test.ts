import { describe, expect, it } from "vitest";
import { ApiError } from "../api/client";
import { taskProblem } from "./taskProblem";

const ar = (a: string) => a;
const en = (_a: string, e: string) => e;

describe("taskProblem", () => {
  it("says a sentence the server wrote as it is", () => {
    const sentence = "ارفع ملف الترجمة الأول من صفحة التاسك، وبعدين دوس «خلصت».";
    expect(taskProblem(new ApiError(400, sentence, { ok: false, error: sentence }), ar)).toBe(sentence);
  });

  it("says a reason given in `message` when there is no sentence in `error`", () => {
    expect(taskProblem(new ApiError(400, "refused", { error: "refused", message: "كلام السيرفر" }), ar)).toBe("كلام السيرفر");
  });

  it("turns each short code into words", () => {
    const words = (code: string, status = 400) => taskProblem(new ApiError(status, code, { error: code }), en);
    expect(words("forbidden", 403)).toBe("You may not do that.");
    expect(words("bad_status")).toBe("The task is not in a state that allows it.");
    expect(words("empty")).toBe("Choose a file first.");
    expect(words("no_room")).toContain("no group with your team leader");
    expect(words("disabled")).toBe("The AI check has been turned off by the admin.");
    expect(words("csrf", 403)).toContain("Reload the page");
    expect(words("refused", 200)).toBe("That could not be done.");
  });

  it("says it could not be done for any other refusal", () => {
    expect(taskProblem(new ApiError(404, "http_404"), en)).toBe("That could not be done.");
    expect(taskProblem(new ApiError(409, "something_new"), en)).toBe("That could not be done.");
  });

  it("is not sure - and does not say it failed - when a server failed or nothing came back", () => {
    for (const error of [new ApiError(500, "server"), new ApiError(502, "http_502"), new TypeError("network down"), "weird"]) {
      expect(taskProblem(error, en)).toContain("not sure");
    }
  });
});
