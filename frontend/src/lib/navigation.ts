/** Leaving the app for a full page load. A seam so tests can watch it. */
export const navigation = {
  assign(url: string): void {
    window.location.assign(url);
  },
};

/** The session is gone: sign in again, and come back to where this was. */
export function redirectToLogin(): void {
  const here = window.location.pathname + window.location.search;
  navigation.assign(`/login/?next=${encodeURIComponent(here)}`);
}
