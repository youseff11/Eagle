/** Leaving the app for a full page load. A seam so tests can watch it. */
export const navigation = {
  assign(url: string): void {
    window.location.assign(url);
  },
};

/**
 * The way into the classic interface that never bounces back here.
 *
 * `/` hands a person whose screen has been ported on to this app; `?classic=1` is passed along to
 * the classic page instead. Every hand-off *to* the classic interface (the check-in screen, an
 * assignment with a clock on it, a ringing call, "the classic interface" in the menu) has to use
 * this address: a plain `/` would be sent straight back, and the person would never see the screen
 * they were sent for.
 */
export const CLASSIC_HOME = "/?classic=1";

/** The session is gone: sign in again, and come back to where this was. */
export function redirectToLogin(): void {
  const here = window.location.pathname + window.location.search;
  navigation.assign(`/login/?next=${encodeURIComponent(here)}`);
}
