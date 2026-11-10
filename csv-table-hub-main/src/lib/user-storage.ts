// Browser storage is shared by everyone who uses the browser, so anything kept in localStorage has to be
// kept per signed-in tenant and user (#176, BR-36). Sign-out removes only the session token, so a key
// that isn't scoped here would show the next person to sign in the previous one's data.

import { getSession } from "./session";

/** `base` scoped to the signed-in tenant and user, or null when nobody is signed in (store nothing). */
export function userKey(base: string): string | null {
  const s = getSession();
  return s ? `${base}:${encodeURIComponent(s.tenant)}:${encodeURIComponent(s.username)}` : null;
}

/**
 * Remove the unscoped entry an earlier version wrote under `base`: it holds some tenant's data and there
 * is no telling whose, so it is dropped, not handed to whoever signs in next.
 */
export function dropUnscoped(base: string): void {
  try {
    window.localStorage.removeItem(base);
  } catch {
    /* storage unavailable: nothing to drop */
  }
}
