// src/__tests__/session.test.ts
// Frontend sign-in (#96): the browser holds a per-user session token, never
// the shared API key; an ended session sends the user back to sign-in.

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { isRedirect } from "@tanstack/react-router";
import {
  authHeaders,
  clearSession,
  getSession,
  requireSession,
  signIn,
  signOut,
  type Session,
} from "@/lib/session";
import { listCsvFiles } from "@/lib/csv.functions";

const future = () => new Date(Date.now() + 3_600_000).toISOString();
const session = (over: Partial<Session> = {}): Session => ({
  token: "tok-123",
  expiresAt: future(),
  username: "alice",
  tenant: "acme",
  role: "uploader",
  ...over,
});
const store = (s: Session) => sessionStorage.setItem("te.session", JSON.stringify(s));
const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });

beforeEach(() => clearSession());
afterEach(() => vi.unstubAllGlobals());

describe("getSession", () => {
  it("is null when nobody has signed in", () => {
    expect(getSession()).toBeNull();
  });

  it("returns a live session", () => {
    store(session());
    expect(getSession()?.username).toBe("alice");
  });

  it("drops an expired session", () => {
    store(session({ expiresAt: new Date(Date.now() - 1000).toISOString() }));
    expect(getSession()).toBeNull();
    expect(sessionStorage.getItem("te.session")).toBeNull();
  });

  it("treats unreadable storage as signed out", () => {
    sessionStorage.setItem("te.session", "{not json");
    expect(getSession()).toBeNull();
  });
});

describe("signIn / signOut", () => {
  it("stores the session the API returns", async () => {
    const fetchMock = vi.fn(async () => json(session()));
    vi.stubGlobal("fetch", fetchMock);
    await signIn("acme", "alice", "pw");
    expect(getSession()?.tenant).toBe("acme");
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toMatch(/\/api\/auth\/login$/);
    expect(JSON.parse(init.body as string)).toEqual({
      tenant: "acme",
      username: "alice",
      password: "pw",
    });
  });

  it("rejects with one generic message on 401 and stores nothing", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => json({ detail: "Invalid tenant, username or password" }, 401)),
    );
    await expect(signIn("acme", "alice", "wrong")).rejects.toThrow(
      "Invalid tenant, username or password",
    );
    expect(getSession()).toBeNull();
  });

  it("sign-out revokes the token on the server and forgets it here", async () => {
    store(session());
    const fetchMock = vi.fn(async () => json({ status: "ok" }));
    vi.stubGlobal("fetch", fetchMock);
    await signOut();
    expect(getSession()).toBeNull();
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toMatch(/\/api\/auth\/logout$/);
    expect((init.headers as Record<string, string>).Authorization).toBe("Bearer tok-123");
  });
});

describe("API calls", () => {
  it("send the bearer token and never an X-API-Key", async () => {
    store(session());
    const fetchMock = vi.fn(async () => json([]));
    vi.stubGlobal("fetch", fetchMock);
    await listCsvFiles();
    const headers = (fetchMock.mock.calls[0] as unknown as [string, RequestInit])[1]
      .headers as Record<string, string>;
    expect(headers.Authorization).toBe("Bearer tok-123");
    expect(Object.keys(headers).map((h) => h.toLowerCase())).not.toContain("x-api-key");
  });

  it("send no Authorization header when signed out", () => {
    expect(authHeaders()).toEqual({});
  });

  it("a 401 ends the session and sends the user to sign-in", async () => {
    store(session());
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => json({ detail: "Session expired or invalid; sign in again" }, 401)),
    );
    const assign = vi.fn();
    vi.stubGlobal("location", { ...window.location, assign });
    await expect(listCsvFiles()).rejects.toThrow("Your session has ended");
    expect(getSession()).toBeNull();
    expect(assign).toHaveBeenCalledWith("/auth");
  });
});

describe("requireSession (route guard)", () => {
  it("redirects to /auth when signed out", () => {
    let thrown: unknown;
    try {
      requireSession();
    } catch (e) {
      thrown = e;
    }
    expect(isRedirect(thrown)).toBe(true);
    expect((thrown as { options: { to: string } }).options.to).toBe("/auth");
  });

  it("lets a signed-in user through", () => {
    store(session());
    expect(() => requireSession()).not.toThrow();
  });
});
