import { describe, expect, it } from "vitest";
import { insertMention, matching, MAX_MENTIONS, mentionPattern, named, pieces, typing, type Mentionable } from "./mentions";

const person = (id: number, name: string): Mentionable => ({ id, name, initials: name.slice(0, 1), role: "translator" });
const mona = person(8, "Mona");
const sam = person(9, "Sam");

describe("an @ being typed", () => {
  it("is found at the start of the words and after a space or a new line", () => {
    expect(typing("@", 1)).toEqual({ start: 0, query: "" });
    expect(typing("hello @mo", 9)).toEqual({ start: 6, query: "mo" });
    expect(typing("line\n@sa", 8)).toEqual({ start: 5, query: "sa" });
  });

  it("is looked for at the cursor, not at the end of the words", () => {
    expect(typing("hello @mo and more", 9)).toEqual({ start: 6, query: "mo" });
    expect(typing("hello @mo and more", 3)).toBeNull();
  });

  it("is not an e-mail address, a second @, or something that went on too long", () => {
    expect(typing("write to me@example.com", 23)).toBeNull();
    expect(typing("@@", 2)).toBeNull();
    expect(typing("@mona\nnext", 10)).toBeNull();
    expect(typing(`@${"x".repeat(31)}`, 32)).toBeNull();
    expect(typing("no at sign here", 5)).toBeNull();
  });

  it("may have a space in it: a full name is looked for as it is typed", () => {
    expect(typing("@Mona Sa", 8)).toEqual({ start: 0, query: "Mona Sa" });
  });
});

describe("who an @ offers", () => {
  const all = [person(1, "Hadi Mona"), mona, sam, person(2, "Omar")];

  it("is everybody for a bare @", () => {
    expect(matching(all, "")).toEqual(all);
    expect(matching(all, "   ")).toEqual(all);
  });

  it("puts the names that start with what was typed before the ones that only hold it, whatever the case", () => {
    expect(matching(all, "mo").map((one) => one.name)).toEqual(["Mona", "Hadi Mona"]);
    expect(matching(all, "SAM").map((one) => one.name)).toEqual(["Sam"]);
    expect(matching(all, "zzz")).toEqual([]);
  });
});

describe("putting a name in", () => {
  it("replaces the @ and what was typed after it, adds a space, and says where the cursor goes", () => {
    expect(insertMention("hi @mo", 3, 6, "Mona")).toEqual({ text: "hi @Mona ", caret: 9 });
    expect(insertMention("@ and the rest", 0, 1, "Sam")).toEqual({ text: "@Sam  and the rest", caret: 5 });
  });
});

describe("a name as a whole word", () => {
  it("is not found inside a longer one - in Arabic too", () => {
    expect(mentionPattern("Nour").test("@Nourhan")).toBe(false);
    expect(mentionPattern("Nour").test("hi @Nour!")).toBe(true);
    expect(mentionPattern("نور").test("@نورهان")).toBe(false);
    expect(mentionPattern("نور").test("يا @نور شوفي")).toBe(true);
    expect(mentionPattern("Nour").test("me@Nour")).toBe(false);
  });

  it("takes a name with characters a pattern would read as its own", () => {
    expect(mentionPattern("Dr. (Ali)").test("ping @Dr. (Ali) now")).toBe(true);
    expect(mentionPattern("A+B").test("@AAB")).toBe(false);
  });
});

describe("who a message is sent with", () => {
  it("is the people picked whose @name is still in the words", () => {
    const picked = [{ id: 8, name: "Mona" }, { id: 9, name: "Sam" }];
    expect(named("@Mona and @Sam look", picked)).toEqual(picked);
    // Taking a name out takes the ping with it.
    expect(named("@Mona look", picked)).toEqual([{ id: 8, name: "Mona" }]);
    expect(named("nobody", picked)).toEqual([]);
  });

  it("is each person once", () => {
    const picked = [{ id: 8, name: "Mona" }, { id: 8, name: "Mona" }];
    expect(named("@Mona @Mona", picked)).toEqual([{ id: 8, name: "Mona" }]);
  });

  it("counts a name typed by hand when only one person in the group has it", () => {
    expect(named("@Mona look", [], [mona, sam])).toEqual([{ id: 8, name: "Mona" }]);
  });

  it("needs the list for two people of the same name: which one was meant is for the person to say", () => {
    const twin = person(10, "Mona");
    expect(named("@Mona look", [], [mona, twin])).toEqual([]);
    expect(named("@Mona look", [{ id: 10, name: "Mona" }], [mona, twin])).toEqual([{ id: 10, name: "Mona" }]);
  });

  it("does not read a short name out of a longer one that was picked", () => {
    const nour = person(1, "Nour");
    const ali = person(2, "Nour Ali");
    expect(named("@Nour Ali look", [{ id: 2, name: "Nour Ali" }], [nour, ali])).toEqual([{ id: 2, name: "Nour Ali" }]);
    // And by hand, the long name covers the short one.
    expect(named("@Nour Ali look", [], [nour, ali])).toEqual([{ id: 2, name: "Nour Ali" }]);
    // While the short one alone is the short one.
    expect(named("@Nour look", [], [nour, ali])).toEqual([{ id: 1, name: "Nour" }]);
  });

  it("is no more people than the server allows", () => {
    const crowd = Array.from({ length: MAX_MENTIONS + 5 }, (_unused, index) => person(100 + index, `Person${String.fromCharCode(65 + index)}`));
    const body = crowd.map((one) => `@${one.name}`).join(" ");
    expect(named(body, [], crowd)).toHaveLength(MAX_MENTIONS);
  });
});

describe("the words of a message, cut for drawing", () => {
  it("marks the people the message mentions and leaves the rest as it is", () => {
    expect(pieces("hi @Mona, and @Sam!", [{ id: 8, name: "Mona" }, { id: 9, name: "Sam" }])).toEqual([
      { text: "hi " },
      { text: "@Mona", mention: { id: 8, name: "Mona" } },
      { text: ", and " },
      { text: "@Sam", mention: { id: 9, name: "Sam" } },
      { text: "!" },
    ]);
  });

  it("leaves an @ nobody was pinged for as plain words", () => {
    expect(pieces("hi @Omar", [{ id: 8, name: "Mona" }])).toEqual([{ text: "hi @Omar" }]);
    expect(pieces("hi @Omar", [])).toEqual([{ text: "hi @Omar" }]);
    expect(pieces("hi @Omar", undefined)).toEqual([{ text: "hi @Omar" }]);
    expect(pieces("", [{ id: 8, name: "Mona" }])).toEqual([{ text: "" }]);
  });

  it("marks every place a name is written, and the longer of two overlapping names wins", () => {
    expect(pieces("@Nour @Nour", [{ id: 1, name: "Nour" }]).filter((piece) => piece.mention)).toHaveLength(2);
    const both = pieces("@Nour Ali", [{ id: 1, name: "Nour" }, { id: 2, name: "Nour Ali" }]);
    expect(both).toEqual([{ text: "@Nour Ali", mention: { id: 2, name: "Nour Ali" } }]);
  });

  it("gives back the words whole when the pieces are put together", () => {
    const body = "يا @نور شوفي الملف مع @Sam (ضروري)";
    const cut = pieces(body, [{ id: 1, name: "نور" }, { id: 9, name: "Sam" }]);
    expect(cut.map((piece) => piece.text).join("")).toBe(body);
    expect(cut.filter((piece) => piece.mention).map((piece) => piece.text)).toEqual(["@نور", "@Sam"]);
  });
});
