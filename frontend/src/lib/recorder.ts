/**
 * The browser's microphone, as little of it as the chat needs (chat slice 3c-2: voice notes).
 *
 * Browsers do not agree on what they can record. Firefox gives Ogg/Opus and Safari MP4/AAC, which WhatsApp takes
 * as they are; Chrome gives WebM, which the server converts before it goes out. The first format the browser says
 * it can record is used, in that order.
 *
 * Nothing here keeps the microphone: it is let go the moment a recording is stopped or dropped, so the browser's
 * "recording" mark goes out with the red dot.
 */

/** The longest recording, in seconds, until the server says (`me.limits.voice`). */
export const MAX_RECORDING_SECONDS = 300;

const TYPES = [
  { mime: "audio/ogg;codecs=opus", extension: ".ogg" },
  { mime: "audio/mp4", extension: ".m4a" },
  { mime: "audio/webm;codecs=opus", extension: ".webm" },
  { mime: "audio/webm", extension: ".webm" },
];

/** A recording, as it is held until it is sent: the sound, how long it ran, and the extension that names its format. */
export interface Recorded {
  blob: Blob;
  seconds: number;
  extension: string;
}

export type RecorderFailure = "unsupported" | "denied" | "failed";

export class RecorderError extends Error {
  readonly code: RecorderFailure;

  constructor(code: RecorderFailure) {
    super(code);
    this.name = "RecorderError";
    this.code = code;
  }
}

/** A recording that is running. */
export interface Recording {
  /** Stop, let the microphone go, and hand back what was heard. */
  stop(): Promise<{ blob: Blob; extension: string }>;
  /** Drop it: the microphone is let go and nothing is kept. */
  cancel(): void;
}

/** `m:ss`, as the player shows a length. */
export function formatSeconds(seconds: number): string {
  const total = Math.max(0, Math.floor(seconds));
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, "0")}`;
}

/** The format to ask the browser for, or `null` when it has no recorder at all. */
function pickType(): { mime: string; extension: string } | null {
  if (typeof window === "undefined" || !("MediaRecorder" in window)) return null;
  for (const type of TYPES) {
    try {
      if (MediaRecorder.isTypeSupported(type.mime)) return type;
    } catch {
      // An older browser throws instead of answering false.
    }
  }
  // It can record, and will not say what: let it choose, and name the file by what it chose.
  return { mime: "", extension: ".webm" };
}

function extensionOf(mime: string, fallback: string): string {
  const kind = mime.toLowerCase();
  if (kind.includes("ogg")) return ".ogg";
  if (kind.includes("mp4") || kind.includes("aac")) return ".m4a";
  if (kind.includes("webm")) return ".webm";
  return fallback;
}

/** Whether this browser can record at all (it still has to be allowed to). */
export function recordingSupported(): boolean {
  return pickType() !== null && typeof navigator !== "undefined" && Boolean(navigator.mediaDevices?.getUserMedia);
}

/** Ask for the microphone and start recording. Rejects with a `RecorderError` saying why not. */
export async function startRecording(): Promise<Recording> {
  const type = pickType();
  if (!type || !navigator.mediaDevices?.getUserMedia) throw new RecorderError("unsupported");

  let stream: MediaStream;
  try {
    stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  } catch (error) {
    const name = error instanceof Error ? error.name : "";
    throw new RecorderError(name === "NotAllowedError" || name === "SecurityError" ? "denied" : "failed");
  }

  const release = () => stream.getTracks().forEach((track) => track.stop());
  let recorder: MediaRecorder;
  try {
    recorder = type.mime ? new MediaRecorder(stream, { mimeType: type.mime }) : new MediaRecorder(stream);
  } catch {
    release();
    throw new RecorderError("failed");
  }

  const chunks: Blob[] = [];
  recorder.ondataavailable = (event) => {
    if (event.data && event.data.size > 0) chunks.push(event.data);
  };
  recorder.start();

  return {
    stop: () =>
      new Promise((resolve, reject) => {
        recorder.onstop = () => {
          release();
          const mime = recorder.mimeType || type.mime || "audio/webm";
          const blob = new Blob(chunks, { type: mime });
          if (blob.size === 0) reject(new RecorderError("failed"));
          else resolve({ blob, extension: extensionOf(mime, type.extension) });
        };
        if (recorder.state === "inactive") {
          release();
          reject(new RecorderError("failed"));
          return;
        }
        recorder.stop();
      }),
    cancel: () => {
      // What the recorder was going to say about being stopped is not wanted.
      recorder.ondataavailable = null;
      recorder.onstop = null;
      if (recorder.state !== "inactive") {
        try {
          recorder.stop();
        } catch {
          // Already gone.
        }
      }
      release();
    },
  };
}
