/**
 * The emoji the chat offers, as code points.
 *
 * They are written as numbers because the project keeps emoji out of its source (`.claude/verify.py` reads every file for them),
 * and a number is what an emoji is: `String.fromCodePoint`. A glyph that is a symbol on its own (a heart, a check mark) carries
 * the variation selector after it, which is what turns it into the picture.
 */
type Code = number | number[];

/** The variation selector that makes the character before it an emoji. */
const PICTURE = 0xfe0f;

const span = (from: number, to: number): Code[] => Array.from({ length: to - from + 1 }, (_, index) => from + index);

export interface EmojiGroup {
  key: string;
  label: [string, string];
  /** The emoji that stands for the group on its tab. */
  tab: string;
  emoji: string[];
}

/** One emoji, from the numbers it is made of. */
export function glyph(code: Code): string {
  return String.fromCodePoint(...(Array.isArray(code) ? code : [code]));
}

const build = (codes: Code[]) => codes.map(glyph);

export const GROUPS: EmojiGroup[] = [
  {
    key: "faces",
    label: ["وشوش", "Faces"],
    tab: glyph(0x1f642),
    emoji: build(span(0x1f600, 0x1f644)),
  },
  {
    key: "hands",
    label: ["إيدين", "Hands"],
    tab: glyph(0x1f44d),
    emoji: build([
      0x1f44d, 0x1f44e, 0x1f44f, 0x1f64c, 0x1f64f, 0x1f44c, [0x270c, PICTURE], 0x1f91d, 0x1f4aa, 0x1f44b, 0x1f44a, [0x270b, PICTURE],
      0x1f91e, [0x261d, PICTURE], 0x1f449, 0x1f448, 0x1f446, 0x1f447, 0x1f590, 0x1f64b, 0x1f926, 0x1f937,
    ]),
  },
  {
    key: "hearts",
    label: ["قلوب", "Hearts"],
    tab: glyph([0x2764, PICTURE]),
    emoji: build([
      [0x2764, PICTURE], 0x1f499, 0x1f49a, 0x1f49b, 0x1f49c, 0x1f9e1, 0x1f5a4, 0x1f90d, 0x1f494, 0x1f495, 0x1f496, 0x1f497, 0x1f498,
      0x1f49d, 0x1f48b, 0x1f339, 0x1f31f, 0x2728, 0x1f525, 0x1f4af,
    ]),
  },
  {
    key: "work",
    label: ["شغل", "Work"],
    tab: glyph(0x1f4bc),
    emoji: build([
      0x2705, 0x274c, [0x26a0, PICTURE], 0x2753, 0x2757, 0x1f4a1, 0x1f50d, 0x1f4ce, 0x1f4c4, 0x1f4c1, 0x1f4cc, 0x1f4dd, 0x1f4c5,
      0x23f0, 0x1f4e7, 0x1f4de, 0x1f4bb, 0x1f4f1, 0x1f512, 0x1f4ca, 0x1f4c8, 0x1f4b0, 0x1f389, 0x1f381, 0x1f3c6, 0x1f680, 0x2615, 0x1f60e,
    ]),
  },
];

/** What a person used last, kept in their own browser: a convenience, so a browser that will not keep it only loses the shortcut. */
const KEY = "eagle.emoji.recent";
const MAX_RECENT = 16;

export function readRecent(): string[] {
  try {
    const stored: unknown = JSON.parse(window.localStorage.getItem(KEY) ?? "[]");
    if (!Array.isArray(stored)) return [];
    // Only what this picker could have written: short and a string, never a word a page could draw as something else.
    const known = new Set(GROUPS.flatMap((group) => group.emoji));
    return stored.filter((one): one is string => typeof one === "string" && known.has(one)).slice(0, MAX_RECENT);
  } catch {
    return [];
  }
}

/** Put an emoji first among the recent ones; the new list, which is also what is kept. */
export function pushRecent(emoji: string): string[] {
  const next = [emoji, ...readRecent().filter((one) => one !== emoji)].slice(0, MAX_RECENT);
  try {
    window.localStorage.setItem(KEY, JSON.stringify(next));
  } catch {
    // No storage here: the list lives for as long as the picker does.
  }
  return next;
}
