import { useCallback, useEffect, useRef, useState } from "react";
import { RecorderError, startRecording, type Recorded, type RecorderFailure, type Recording } from "../lib/recorder";

export type VoicePhase = "idle" | "starting" | "recording" | "ready";

/** What the person sees while they record: nothing, the microphone being asked for, recording, or a take to listen to. */
export interface Voice {
  phase: VoicePhase;
  /** How long the recording has run, or how long the take is. */
  seconds: number;
  /** The finished take, once there is one. */
  recorded: Recorded | null;
  /** A playable address for the take. */
  url: string;
  /** Why the last attempt did not start, or nothing. */
  failure: RecorderFailure | "";
  start: () => void;
  /** Stop recording: the take is kept to be listened to. */
  stop: () => void;
  /** Throw the recording or the take away. */
  discard: () => void;
}

function addressOf(blob: Blob): string {
  return typeof URL !== "undefined" && typeof URL.createObjectURL === "function" ? URL.createObjectURL(blob) : "";
}

function forget(url: string): void {
  if (url && typeof URL !== "undefined" && typeof URL.revokeObjectURL === "function") URL.revokeObjectURL(url);
}

/**
 * One recording at a time, with a clock: record, stop (or run out of time: `maxSeconds`), listen, then send or throw it
 * away. Leaving the page while it runs lets the microphone go.
 *
 * The clock is the clock on the wall, not a count of timer ticks: a tab in the background has its timers slowed,
 * and a recording that is counted by them runs past its limit and is reported shorter than it was.
 */
export function useVoiceRecorder(maxSeconds: number): Voice {
  const [phase, setPhase] = useState<VoicePhase>("idle");
  const [seconds, setSeconds] = useState(0);
  const [recorded, setRecorded] = useState<Recorded | null>(null);
  const [url, setUrl] = useState("");
  const [failure, setFailure] = useState<RecorderFailure | "">("");

  const active = useRef<Recording | null>(null);
  const startedAt = useRef(0);
  const timer = useRef<number | null>(null);
  const address = useRef("");
  const starting = useRef(false);
  const alive = useRef(true);
  // Moves each time a recording is thrown away: an answer that was on its way for the one before is not wanted.
  const generation = useRef(0);
  // The latest `stop`, for the recorder to call when it ends by itself.
  const ending = useRef<() => void>(() => undefined);

  const elapsed = useCallback(() => Math.floor((Date.now() - startedAt.current) / 1000), []);

  const stopClock = useCallback(() => {
    if (timer.current !== null) {
      window.clearInterval(timer.current);
      timer.current = null;
    }
  }, []);

  const dropAddress = useCallback(() => {
    forget(address.current);
    address.current = "";
  }, []);

  const stop = useCallback(() => {
    const running = active.current;
    if (!running) return;
    active.current = null;
    stopClock();
    const length = Math.max(1, Math.round((Date.now() - startedAt.current) / 1000));
    const mine = generation.current;
    running.stop().then(
      ({ blob, extension }) => {
        // Gone while it was being stopped, or thrown away in that moment: the take is not wanted.
        if (!alive.current || mine !== generation.current) return;
        dropAddress();
        address.current = addressOf(blob);
        setRecorded({ blob, extension, seconds: length });
        setUrl(address.current);
        setPhase("ready");
      },
      () => {
        if (!alive.current || mine !== generation.current) return;
        setFailure("failed");
        setSeconds(0);
        setPhase("idle");
      },
    );
  }, [dropAddress, stopClock]);
  ending.current = stop;

  const start = useCallback(() => {
    if (starting.current || active.current || phase === "ready") return;
    starting.current = true;
    setFailure("");
    setPhase("starting");
    const mine = generation.current;
    startRecording(() => ending.current()).then(
      (recording) => {
        starting.current = false;
        // Asked for, and the person went elsewhere (or gave it up) while the browser was asking: the microphone is
        // not wanted.
        if (!alive.current || mine !== generation.current) {
          recording.cancel();
          return;
        }
        active.current = recording;
        startedAt.current = Date.now();
        setSeconds(0);
        setPhase("recording");
        timer.current = window.setInterval(() => {
          const now = elapsed();
          setSeconds(now);
          if (now >= maxSeconds) ending.current();
        }, 1000);
      },
      (error: unknown) => {
        starting.current = false;
        if (!alive.current || mine !== generation.current) return;
        setFailure(error instanceof RecorderError ? error.code : "failed");
        setPhase("idle");
      },
    );
  }, [elapsed, maxSeconds, phase]);

  const discard = useCallback(() => {
    generation.current += 1;
    stopClock();
    active.current?.cancel();
    active.current = null;
    dropAddress();
    setRecorded(null);
    setUrl("");
    setSeconds(0);
    setPhase("idle");
    starting.current = false;
  }, [dropAddress, stopClock]);

  // Leaving the conversation lets the microphone go and drops what was heard.
  useEffect(() => {
    // Set again on every mount: a development build mounts, unmounts and mounts a component to prove it can.
    alive.current = true;
    return () => {
      alive.current = false;
      stopClock();
      active.current?.cancel();
      active.current = null;
      forget(address.current);
    };
  }, [stopClock]);

  return { phase, seconds: phase === "ready" ? (recorded?.seconds ?? seconds) : seconds, recorded, url, failure, start, stop, discard };
}
