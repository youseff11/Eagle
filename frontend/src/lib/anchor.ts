/**
 * Landing on a part of a page: the address ends in `#id` (the menu's search sends you to a section of the settings page).
 *
 * The page may still be asking the server for what it draws, so the part is waited for rather than looked for once;
 * when it is there it is scrolled to and lit for a moment (`.is-found`, in the design system) so the eye finds it.
 * A field is lit by its whole box (the label and the hint with it), not by the bare input.
 */

/** How long to wait for the part to be drawn before giving up. */
const WAIT_MS = 6000;

/** Light up and scroll to what `id` names. */
export function landOn(target: HTMLElement): void {
  const box = (target.closest(".field") as HTMLElement | null) ?? target;
  box.classList.remove("is-found");
  // Reading a layout property makes the browser start the pulse again when the same part is asked for twice.
  void box.offsetWidth;
  box.classList.add("is-found");
  if (typeof box.scrollIntoView === "function") box.scrollIntoView({ behavior: "smooth", block: "start" });
}

/**
 * Land on `id` as soon as it is on the page. Returns what stops the waiting (the page changed first).
 * `id` is the part after the `#`, undecoded.
 */
export function landWhenDrawn(id: string): () => void {
  let name = id;
  try {
    name = decodeURIComponent(id);
  } catch {
    // A stray percent sign in a hand-written address: look for it as it is.
  }
  if (!name) return () => undefined;

  const find = () => document.getElementById(name);
  const now = find();
  if (now) {
    landOn(now);
    return () => undefined;
  }

  const watcher = new MutationObserver(() => {
    const found = find();
    if (!found) return;
    stop();
    landOn(found);
  });
  const timer = window.setTimeout(() => stop(), WAIT_MS);
  function stop() {
    watcher.disconnect();
    window.clearTimeout(timer);
  }
  watcher.observe(document.body, { childList: true, subtree: true });
  return stop;
}
