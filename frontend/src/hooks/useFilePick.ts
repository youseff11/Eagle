import { useCallback, useEffect, useMemo, useState } from "react";
import type { ThreadEntry, ThreadFile } from "../api/types";
import type { FileMark } from "../components/chat/Bubble";

/** A file of a client's message that can be picked: a document the operation may make a task of (not a voice note). */
export function pickable(entry: ThreadEntry, file: ThreadFile): boolean {
  return entry.actions && file.id > 0 && !file.audio;
}

/**
 * "Select files": a box on every file in a client's conversation; whatever is ticked, across any number of messages,
 * becomes one task (or is forwarded). The server re-checks every id against the messages and the client, so this
 * only has to be convenient. A day is a selection of its own: choosing one ticks that day's files and nothing else,
 * and "select all" then works inside the chosen day. A file that has gone from the thread is not kept ticked.
 */
export function useFilePick(messages: ThreadEntry[]) {
  const [picking, setPicking] = useState(false);
  /** File id -> the id of the message it is in, for everything ticked. */
  const [picked, setPicked] = useState<Record<number, number>>({});
  const [day, setDay] = useState("");

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

  const start = useCallback(() => {
    setPicking(true);
    setPicked({});
    setDay("");
  }, []);
  const stop = useCallback(() => {
    setPicking(false);
    setPicked({});
    setDay("");
  }, []);

  const toggle = (message: number, file: number) =>
    setPicked((now) => {
      const next = { ...now };
      if (file in next) delete next[file];
      else next[file] = message;
      return next;
    });

  const chooseDay = (value: string) => {
    setDay(value);
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
  const messageIds = [...new Set(Object.values(picked))];

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

  return { picking, start, stop, available: files.length > 0, days, day: chosenDay, chooseDay, allIn, toggleAll, ids, messageIds, mark };
}
