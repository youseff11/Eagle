import { useCallback, useEffect, useMemo, useState } from "react";
import type { ThreadEntry, ThreadFile } from "../api/types";
import type { FileMark, TextMark } from "../components/chat/Bubble";

/** A file of a client's message that can be picked: a document the operation may make a task of (not a voice note). */
export function pickable(entry: ThreadEntry, file: ThreadFile): boolean {
  return entry.actions && file.id > 0 && !file.audio;
}

/** A message of the client's with words in it: it can be ticked to be written in the task's details. */
export function wordedMessage(entry: ThreadEntry): boolean {
  return entry.kind === "in" && entry.actions && entry.id > 0 && entry.body.trim() !== "";
}

/**
 * "Select files": a box on every file in a client's conversation; whatever is ticked, across any number of messages,
 * becomes one task (or is forwarded). The server re-checks every id against the messages and the client, so this
 * only has to be convenient. A day is a selection of its own: choosing one ticks that day's files and nothing else,
 * and "select all" then works inside the chosen day. A file that has gone from the thread is not kept ticked.
 *
 * The words of a message can be ticked as well (`texts`): those messages are written in the task's details, and are
 * part of the task even when none of their files is ticked. Nothing ticked there is every ticked file's own message.
 */
export function useFilePick(messages: ThreadEntry[]) {
  const [picking, setPicking] = useState(false);
  /** File id -> the id of the message it is in, for everything ticked. */
  const [picked, setPicked] = useState<Record<number, number>>({});
  /** The ids of the messages ticked for the details. */
  const [texts, setTexts] = useState<number[]>([]);
  const [day, setDay] = useState("");

  const wordedSignature = messages.filter(wordedMessage).map((entry) => entry.id).join(",");

  const files = useMemo(
    () => messages.flatMap((entry) => entry.files.filter((file) => pickable(entry, file)).map((file) => ({ file: file.id, message: entry.id, date: entry.date }))),
    [messages],
  );
  const signature = files.map((one) => one.file).join(",");

  // Days that really have a file to tick, newest first, each with how many.
  const days = useMemo(() => {
    const counts = new Map<string, number>();
    for (const one of files) counts.set(one.date, (counts.get(one.date) ?? 0) + 1);
    return [...counts.entries()].sort((a, b) => (a[0] < b[0] ? 1 : -1)).map(([date, count]) => ({ date, count }));
  }, [files]);
  const chosenDay = days.some((one) => one.date === day) ? day : "";
  const inDay = files.filter((one) => !chosenDay || one.date === chosenDay);
  const allIn = inDay.length > 0 && inDay.every((one) => one.file in picked);

  useEffect(() => {
    const here = new Set(signature === "" ? [] : signature.split(",").map(Number));
    setPicked((now) => {
      const kept = Object.keys(now).filter((id) => here.has(Number(id)));
      return kept.length === Object.keys(now).length ? now : Object.fromEntries(kept.map((id) => [id, now[Number(id)]!]));
    });
  }, [signature]);

  // A message that has gone from the thread is not kept ticked either.
  useEffect(() => {
    const here = new Set(wordedSignature === "" ? [] : wordedSignature.split(",").map(Number));
    setTexts((now) => (now.every((id) => here.has(id)) ? now : now.filter((id) => here.has(id))));
  }, [wordedSignature]);

  const start = useCallback(() => {
    setPicking(true);
    setPicked({});
    setTexts([]);
    setDay("");
  }, []);
  const stop = useCallback(() => {
    setPicking(false);
    setPicked({});
    setTexts([]);
    setDay("");
  }, []);

  const toggleText = (message: number) => setTexts((now) => (now.includes(message) ? now.filter((id) => id !== message) : [...now, message]));

  const toggle = (message: number, file: number) =>
    setPicked((now) => {
      const next = { ...now };
      if (file in next) delete next[file];
      else next[file] = message;
      return next;
    });

  const chooseDay = (value: string) => {
    setDay(value);
    setTexts([]);
    setPicked(value ? Object.fromEntries(files.filter((one) => one.date === value).map((one) => [one.file, one.message])) : {});
  };

  const toggleAll = () =>
    setPicked((now) => {
      const next = { ...now };
      for (const one of inDay) {
        if (allIn) delete next[one.file];
        else next[one.file] = one.message;
      }
      return next;
    });

  const ids = Object.keys(picked).map(Number);
  // The messages of the task: those with a ticked file, and those ticked for the details.
  const messageIds = [...new Set([...Object.values(picked), ...texts])].sort((a, b) => a - b);
  const textIds = [...texts].sort((a, b) => a - b);

  const mark: FileMark | undefined =
    files.length > 0
      ? {
          mode: "pick",
          active: picking,
          show: pickable,
          ticked: (file) => file.id in picked,
          toggle: (entry, file) => toggle(entry.id, file.id),
        }
      : undefined;

  const textMark: TextMark | undefined = files.length > 0 ? { active: picking, show: wordedMessage, ticked: (entry) => texts.includes(entry.id), toggle: (entry) => toggleText(entry.id) } : undefined;

  return { picking, start, stop, available: files.length > 0, days, day: chosenDay, chooseDay, allIn, toggleAll, ids, messageIds, texts: textIds, mark, textMark };
}
