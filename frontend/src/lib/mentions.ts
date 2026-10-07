/**
 * Mentioning a colleague in a work group: "@Name" in the words, and the ids of the people picked beside them.
 *
 * The server is the authority (`services.mention_targets`): it pings a person only if their id was sent, they are in the
 * room and may open it, and "@name" is still in the words. Everything here draws and collects; nothing here decides who is
 * told. The rule for "@name" as a whole word is the server's (`services.mention_pattern`) and is kept in step with it:
 * "@Nour" is not found inside "@Nourhan". `\w` of Python reads any letter or digit in any script, so the same here is
 * `\p{L}\p{N}_` - JavaScript's own `\w` is ASCII and would call an Arabic name's letters "not part of a word".
 */

/** A colleague who can be mentioned: by id, because a name is not unique. */
export interface Mentionable {
  id: number;
  name: string;
  initials: string;
  avatar?: string | null;
  role: string;
}

/** A person a message mentions (`ThreadEntry.mentions`). */
export interface Mentioned {
  id: number;
  name: string;
}

/** The most people one message may mention (`services.MAX_MENTIONS`). */
export const MAX_MENTIONS = 20;

const WORD = "[\\p{L}\\p{N}_]";

function escaped(text: string): string {
  return text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/** `@name` as a whole word, as the server reads it. */
export function mentionPattern(name: string, flags = "u"): RegExp {
  return new RegExp(`(?<!${WORD})@${escaped(name)}(?!${WORD})`, flags);
}

/** The "@..." being typed at the caret: where it starts and what has been typed after the "@". */
export interface Typing {
  start: number;
  query: string;
}

/** Longest thing typed after an "@" that is still taken to be a name being looked for (a full name has a space in it). */
const LOOKING_FOR = 30;

/**
 * Is the caret inside an "@..." that is being typed? An "@" counts only at the start of the words or after a space or a
 * new line (an e-mail address is not a mention), and only while no new line and no second "@" has come after it.
 */
export function typing(text: string, caret: number): Typing | null {
  const before = text.slice(0, caret);
  const at = before.lastIndexOf("@");
  if (at < 0) return null;
  if (at > 0 && !/\s/.test(before[at - 1]!)) return null;
  const query = before.slice(at + 1);
  if (query.length > LOOKING_FOR || /[\n@]/.test(query)) return null;
  return { start: at, query };
}

/** The people whose name has what was typed in it, the ones whose name starts with it first. Nobody for an empty "@": all of them. */
export function matching(people: Mentionable[], query: string): Mentionable[] {
  const needle = query.trim().toLowerCase();
  if (needle === "") return people;
  const starts: Mentionable[] = [];
  const holds: Mentionable[] = [];
  for (const person of people) {
    const name = person.name.toLowerCase();
    if (name.startsWith(needle)) starts.push(person);
    else if (name.includes(needle)) holds.push(person);
  }
  return [...starts, ...holds];
}

/** The words with "@query" (from `start` to the caret) replaced by "@name ", and where the caret goes after it. */
export function insertMention(text: string, start: number, caret: number, name: string): { text: string; caret: number } {
  const inserted = `@${name} `;
  return { text: text.slice(0, start) + inserted + text.slice(caret), caret: start + inserted.length };
}

/**
 * The people a message is sent with: those picked from the list whose "@name" is still in the words (taking the name out
 * takes the ping with it), and then anybody whose full "@name" was typed by hand when only one person in the group has that
 * name (two of the same name need the list, to say which). Each once, no more than the server allows.
 */
export function named(body: string, picked: Mentioned[], people: Mentionable[] = []): Mentioned[] {
  const out: Mentioned[] = [];
  const add = (person: Mentioned) => {
    if (out.length >= MAX_MENTIONS || out.some((one) => one.id === person.id) || !mentionPattern(person.name).test(body)) return;
    out.push({ id: person.id, name: person.name });
  };
  for (const person of picked) add(person);
  // "@Nour" is found inside "@Nour Ali" too: by hand, a name counts only where a longer name does not cover it.
  const unique = people.filter((person) => people.filter((other) => other.name === person.name).length === 1);
  const read = new Set(pieces(body, [...picked, ...unique]).flatMap((piece) => (piece.mention ? [piece.mention.id] : [])));
  for (const person of unique) if (read.has(person.id)) add(person);
  return out;
}

/** A piece of a message's words: plain text, or the "@name" of a person it mentions. */
export type Piece = { text: string; mention?: undefined } | { text: string; mention: Mentioned };

/**
 * The words cut into plain pieces and mentions, for drawing. Only the people the server says the message mentions are
 * marked: an "@name" nobody was pinged for stays plain text. When two names overlap ("@Nour" and "@Nour Ali") the longer
 * one wins, and each place in the words belongs to one mention at most.
 */
export function pieces(body: string, mentions: Mentioned[] | undefined): Piece[] {
  if (!body || !mentions || mentions.length === 0) return [{ text: body }];
  const found: { from: number; to: number; person: Mentioned }[] = [];
  for (const person of [...mentions].sort((a, b) => b.name.length - a.name.length)) {
    const pattern = mentionPattern(person.name, "gu");
    for (let hit = pattern.exec(body); hit !== null; hit = pattern.exec(body)) {
      const from = hit.index;
      const to = from + hit[0].length;
      if (found.some((one) => from < one.to && to > one.from)) continue;
      found.push({ from, to, person });
    }
  }
  if (found.length === 0) return [{ text: body }];
  found.sort((a, b) => a.from - b.from);
  const out: Piece[] = [];
  let at = 0;
  for (const one of found) {
    if (one.from > at) out.push({ text: body.slice(at, one.from) });
    out.push({ text: body.slice(one.from, one.to), mention: one.person });
    at = one.to;
  }
  if (at < body.length) out.push({ text: body.slice(at) });
  return out;
}
