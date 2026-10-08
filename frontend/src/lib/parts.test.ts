import { describe, expect, it } from "vitest";
import { MAX_PARTS, rowProblems, wordsGiven, type PartRow, type TakenShare } from "./parts";

const t = (ar: string, _en: string) => ar;
const names = new Map([
  [1, "Nada"],
  [2, "Sam"],
  [3, "Ola"],
]);

let key = 0;
const row = (over: Partial<PartRow> = {}): PartRow => ({ key: key++, translator: 1, source: "EN", target: "AR", words: "500", from: "", to: "", ...over });
const problems = (rows: PartRow[], taken: TakenShare[] = []) => rowProblems(rows, taken, names, t);

describe("rowProblems: what the leader is told before anything is sent", () => {
  it("has nothing to say about one translator with a pair and words", () => {
    expect(problems([row()])).toEqual([""]);
  });

  it("wants a translator", () => {
    expect(problems([row({ translator: null })])[0]).toBe("اختار مترجم.");
  });

  it("wants both languages", () => {
    expect(problems([row({ source: "  " })])[0]).toBe("حدد الترجمة من لغة إيه لغة إيه.");
    expect(problems([row({ target: "" })])[0]).toBe("حدد الترجمة من لغة إيه لغة إيه.");
  });

  it("wants words that are a whole number above nought", () => {
    for (const bad of ["", "0", "-3", "1.5", "12x", " ", "١٢"]) {
      expect(problems([row({ words: bad })])[0], bad).toBe("اكتب عدد الكلمات (رقم أكبر من صفر).");
    }
    expect(problems([row({ words: " 40 " })])).toEqual([""]);
  });

  it("makes pages optional for one translator, but whole once any are typed", () => {
    expect(problems([row({ from: "3" })])[0]).toBe("اكتب الصفحتين: من وإلى.");
    expect(problems([row({ to: "3" })])[0]).toBe("اكتب الصفحتين: من وإلى.");
    expect(problems([row({ from: "0", to: "3" })])[0]).toBe("اكتب الصفحتين: من وإلى.");
    expect(problems([row({ from: "9", to: "3" })])[0]).toBe("الصفحة الأخيرة لازم تكون بعد الأولى أو نفسها.");
    expect(problems([row({ from: "3", to: "3" })])).toEqual([""]);
  });

  it("asks every translator for pages as soon as there is more than one", () => {
    const two = [row({ translator: 1 }), row({ translator: 2 })];
    expect(problems(two)).toEqual(["اكتب من صفحة كام لحد صفحة كام.", "اكتب من صفحة كام لحد صفحة كام."]);
    const given = [row({ translator: 1, from: "1", to: "10" }), row({ translator: 2, from: "11", to: "20" })];
    expect(problems(given)).toEqual(["", ""]);
  });

  it("counts the shares already taken, so a second translator makes it a shared task", () => {
    const taken: TakenShare[] = [{ name: "Nada", page_from: 1, page_to: 10 }];
    expect(problems([row({ translator: 2 })], taken)[0]).toBe("اكتب من صفحة كام لحد صفحة كام.");
  });

  it("says which colleague the pages overlap, in every way two ranges can touch", () => {
    const first = (from: string, to: string) => problems([row({ translator: 1, from: "5", to: "10" }), row({ translator: 2, from, to })])[1];
    for (const [from, to] of [["10", "12"], ["1", "5"], ["6", "8"], ["1", "20"], ["5", "10"]]) {
      expect(first(from!, to!), `${from}-${to}`).toBe("الصفحات متداخلة مع Nada (5-10).");
    }
    expect(first("11", "12")).toBe("");
    expect(first("1", "4")).toBe("");
  });

  it("holds new pages away from the shares already taken", () => {
    const taken: TakenShare[] = [{ name: "Nada", page_from: 1, page_to: 10 }, { name: "Ola", page_from: 21, page_to: null }];
    expect(problems([row({ translator: 2, from: "8", to: "12" })], taken)[0]).toBe("الصفحات متداخلة مع Nada (1-10).");
    expect(problems([row({ translator: 2, from: "20", to: "21" })], taken)[0]).toBe("الصفحات متداخلة مع Ola (21-21).");
    expect(problems([row({ translator: 2, from: "11", to: "20" })], taken)).toEqual([""]);
  });

  it("does not let one translator be listed twice", () => {
    const rows = [row({ translator: 1, from: "1", to: "5" }), row({ translator: 1, from: "6", to: "9" })];
    expect(problems(rows)[1]).toBe("المترجم ده اتكرر: كل مترجم ليه جزء واحد.");
  });

  it("reports each row on its own place", () => {
    const rows = [row({ translator: 1, from: "1", to: "5" }), row({ translator: 2, words: "", from: "6", to: "9" }), row({ translator: 3, from: "10", to: "12" })];
    expect(problems(rows)).toEqual(["", "اكتب عدد الكلمات (رقم أكبر من صفر).", ""]);
  });
});

describe("wordsGiven", () => {
  it("adds what is a number and ignores what is not", () => {
    expect(wordsGiven([row({ words: "800" }), row({ words: "400" }), row({ words: "x" }), row({ words: "" })])).toBe(1200);
    expect(wordsGiven([])).toBe(0);
  });

  it("agrees with the server about the most translators on a task", () => {
    expect(MAX_PARTS).toBe(10);
  });
});
