// src/lib/session.ts — the signed-in session (ART M2, #96, BR-36).
//
// The browser holds a per-user session token from POST /api/auth/login and
// sends it as `Authorization: Bearer <token>`. It never holds the shared API
// key. The token lives in sessionStorage, so it ends when the tab closes.

import { redirect } from "@tanstack/react-router";

export interface Session {
  token: string;
  expiresAt: string;
  username: string;
  tenant: string;
  role: string;
}

const KEY = "te.session";

export const apiBase = (import.meta.env.VITE_API_BASE ?? "").replace(/\/$/, "");

export function getSession(now: Date = new Date()): Session | null {
  try {
    const raw = sessionStorage.getItem(KEY);
    if (!raw) return null;
    const s = JSON.parse(raw) as Session;
    if (!s.token || new Date(s.expiresAt) <= now) {
      sessionStorage.removeItem(KEY);
      return null;
    }
    return s;
  } catch {
    return null;
  }
}

export function clearSession(): void {
  try {
    sessionStorage.removeItem(KEY);
  } catch {
    /* storage unavailable: nothing to clear */
  }
}

/** Sign in with a local account. Throws with the server's message on failure. */
export async function signIn(tenant: string, username: string, password: string): Promise<Session> {
  const res = await fetch(`${apiBase}/api/auth/login`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ tenant, username, password }),
  });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(
      res.status === 401
        ? "Invalid tenant, username or password"
        : (body?.detail ?? res.statusText),
    );
  }
  const session = body as Session;
  try {
    sessionStorage.setItem(KEY, JSON.stringify(session));
  } catch {
    throw new Error(
      "This browser blocks session storage, so sign-in can't be kept. Allow site data and try again.",
    );
  }
  return session;
}

/** Revoke the session on the server (best effort) and forget it here. */
export async function signOut(): Promise<void> {
  const s = getSession();
  clearSession();
  if (s) {
    await fetch(`${apiBase}/api/auth/logout`, {
      method: "POST",
      headers: { Authorization: `Bearer ${s.token}` },
    }).catch(() => undefined);
  }
}

/** Headers for an API call: the bearer token when signed in. */
export function authHeaders(): Record<string, string> {
  const s = getSession();
  return s ? { Authorization: `Bearer ${s.token}` } : {};
}

/** Route guard (#96): send anyone without a live session to the sign-in page. */
export function requireSession(): void {
  if (!getSession()) throw redirect({ to: "/auth" });
}

/** Change your own password (#117). This session stays; the server ends all others. */
export async function changePassword(currentPassword: string, newPassword: string): Promise<void> {
  const res = await fetch(`${apiBase}/api/auth/password`, {
    method: "POST",
    headers: { "content-type": "application/json", ...authHeaders() },
    body: JSON.stringify({ currentPassword, newPassword }),
  });
  if (res.ok) return;
  const body = await res.json().catch(() => ({}));
  if (res.status === 401) {
    clearSession();
    throw new Error("Your session has ended. Sign in again.");
  }
  throw new Error(
    res.status === 422
      ? `The new password must be at least ${MIN_PASSWORD} characters`
      : (body?.detail ?? res.statusText),
  );
}

export const MIN_PASSWORD = 12;
