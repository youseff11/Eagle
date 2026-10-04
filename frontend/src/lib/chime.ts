/**
 * The notification sound, the same chime the classic pages play (`beep` in the old classic app.js, now deleted):
 * two notes a fifth apart, each a sine with a quiet octave on top so it carries on laptop speakers,
 * through a compressor so it can be loud without clipping. No audio files: it is made with WebAudio.
 *
 * A browser keeps a page silent until the person has clicked or pressed a key in it. The context
 * is therefore made inside that first gesture (`armSound`), never before it: one made earlier stays
 * suspended and the first notification would ring into nothing. Until then `chime` does nothing.
 */

type AudioContextClass = typeof AudioContext;

let context: AudioContext | null = null;
let output: DynamicsCompressorNode | null = null;

function contextClass(): AudioContextClass | undefined {
  const w = window as unknown as { AudioContext?: AudioContextClass; webkitAudioContext?: AudioContextClass };
  return w.AudioContext ?? w.webkitAudioContext;
}

/** Make the context, or wake it. Called from a gesture, and again before every chime. */
function wake(create: boolean): AudioContext | null {
  if (!context) {
    const Ctx = contextClass();
    if (!create || !Ctx) return null;
    try {
      context = new Ctx();
    } catch {
      return null;
    }
  }
  if (context.state === "suspended") void context.resume().catch(() => undefined);
  return context;
}

function compressor(ctx: AudioContext): AudioNode {
  if (!output) {
    const squeeze = ctx.createDynamicsCompressor();
    squeeze.threshold.value = -14;
    squeeze.knee.value = 8;
    squeeze.ratio.value = 6;
    squeeze.attack.value = 0.003;
    squeeze.release.value = 0.2;
    squeeze.connect(ctx.destination);
    output = squeeze;
  }
  return output;
}

function note(ctx: AudioContext, out: AudioNode, hz: number, start: number, length: number, level: number): void {
  for (const [multiple, share] of [
    [1, 1],
    [2, 0.28],
  ] as const) {
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.type = "sine";
    osc.frequency.setValueAtTime(hz * multiple, start);
    gain.gain.setValueAtTime(0.0001, start);
    gain.gain.exponentialRampToValueAtTime(level * share, start + 0.012);
    gain.gain.exponentialRampToValueAtTime(0.0001, start + length);
    osc.connect(gain).connect(out);
    osc.start(start);
    osc.stop(start + length + 0.02);
  }
}

/**
 * Ring the chime `times` times, the first note at `frequency`. `soft` is the quiet one for an
 * ordinary notice; the loud pair is for a notification the server marked with a sound.
 */
export function chime(times = 1, frequency = 880, soft = false): void {
  const ctx = wake(false);
  // A context that is not running is a page nobody has touched yet (or a muted tab): silence.
  if (!ctx || ctx.state !== "running") return;
  try {
    const out = compressor(ctx);
    const level = soft ? 0.35 : 0.9;
    for (let i = 0; i < times; i++) {
      const start = ctx.currentTime + 0.02 + i * 0.55;
      note(ctx, out, frequency, start, 0.32, level);
      note(ctx, out, frequency * 1.5, start + 0.14, 0.42, level);
    }
  } catch {
    /* a sound that cannot play is not worth an error */
  }
}

const GESTURES = ["pointerdown", "keydown", "touchstart"] as const;

/**
 * Let the page make sound from the first click or key press on. Returns the function that removes
 * the listeners (for the component that armed it, and for tests).
 */
export function armSound(): () => void {
  const unlock = () => {
    const ctx = wake(true);
    if (ctx && ctx.state === "running") stop();
    // A context still suspended after the gesture (the browser said no) keeps the listeners:
    // the next gesture tries again.
  };
  const stop = () => {
    for (const name of GESTURES) document.removeEventListener(name, unlock, true);
  };
  for (const name of GESTURES) document.addEventListener(name, unlock, true);
  return stop;
}

/** Forget the context. For tests: a real page keeps one for its whole life. */
export function resetSound(): void {
  void context?.close().catch(() => undefined);
  context = null;
  output = null;
}
