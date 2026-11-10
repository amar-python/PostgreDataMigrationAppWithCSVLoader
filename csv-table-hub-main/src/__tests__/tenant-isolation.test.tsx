// #176 (BR-36): upload history is kept in localStorage under one global key, so the next person
// to sign in on the same browser sees the previous tenant's file names and rejected values.
//
// #176 was closed as moot because the Streamlit migration (#212) replaces this screen, but the
// React app still ships until then. `it.fails` keeps this suite green while the leak exists and
// turns it red the moment it is fixed, so the test is then switched to a plain `it`.

import { act, renderHook } from "@testing-library/react";
import { beforeEach, expect, it } from "vitest";
import { useLocalStorageState } from "@/hooks/use-local-storage";
import { clearSession } from "@/lib/session";

type Job = { name: string };

function signInAs(tenant: string) {
  sessionStorage.setItem(
    "te.session",
    JSON.stringify({
      token: `t-${tenant}`,
      expiresAt: "2099-01-01T00:00:00Z",
      username: `user-${tenant}`,
      tenant,
      role: "uploader",
    }),
  );
}

beforeEach(() => {
  window.localStorage.clear();
  clearSession();
});

it("keeps a tenant's own history across a reload (the feature)", () => {
  signInAs("acme");
  const first = renderHook(() => useLocalStorageState<Job[]>([]));
  act(() => first.result.current[1]([{ name: "acme-payroll.csv" }]));
  first.unmount();

  const reloaded = renderHook(() => useLocalStorageState<Job[]>([]));
  expect(reloaded.result.current[0]).toEqual([{ name: "acme-payroll.csv" }]);
});

it.fails("#176: another tenant signing in on the same browser does not see the previous tenant's history", () => {
  signInAs("acme");
  const acme = renderHook(() => useLocalStorageState<Job[]>([]));
  act(() => acme.result.current[1]([{ name: "acme-payroll.csv" }]));
  acme.unmount();

  clearSession(); // sign out: only the session token is removed
  signInAs("globex");
  const globex = renderHook(() => useLocalStorageState<Job[]>([]));

  expect(globex.result.current[0]).toEqual([]);
});
