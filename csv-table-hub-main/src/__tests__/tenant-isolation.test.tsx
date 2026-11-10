// #176 (BR-36): upload history and saved header-mapping templates were kept in localStorage under one
// global key, so whoever signed in next on the same browser saw the previous tenant's file names, rejected
// values and column names. Both are now kept per signed-in tenant and user.

import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import { useLocalStorageState } from "@/hooks/use-local-storage";
import {
  deleteTemplate,
  loadTemplates,
  saveTemplate,
  type MappingTemplate,
} from "@/lib/mapping-templates";
import { clearSession } from "@/lib/session";

type Job = { name: string };

function signInAs(tenant: string, username = `user-${tenant}`) {
  sessionStorage.setItem(
    "te.session",
    JSON.stringify({
      token: `t-${tenant}-${username}`,
      expiresAt: "2099-01-01T00:00:00Z",
      username,
      tenant,
      role: "uploader",
    }),
  );
}

const template = (name: string): MappingTemplate => ({
  id: name,
  name,
  columns: [{ original: "salary", renamed: "", type: "numeric" }],
  createdAt: 1,
});

function rememberHistory(job: string) {
  const hook = renderHook(() => useLocalStorageState<Job[]>([]));
  act(() => hook.result.current[1]([{ name: job }]));
  hook.unmount();
}

const history = () => renderHook(() => useLocalStorageState<Job[]>([])).result.current[0];

beforeEach(() => {
  window.localStorage.clear();
  clearSession();
});

describe("upload history", () => {
  it("keeps a user's own history across a reload (the feature)", () => {
    signInAs("acme");
    rememberHistory("acme-payroll.csv");
    expect(history()).toEqual([{ name: "acme-payroll.csv" }]);
  });

  it("does not show another tenant the previous tenant's history", () => {
    signInAs("acme");
    rememberHistory("acme-payroll.csv");
    clearSession(); // sign out removes only the session token
    signInAs("globex");
    expect(history()).toEqual([]);
  });

  it("does not show another user of the same tenant someone else's history", () => {
    signInAs("acme", "alice");
    rememberHistory("alice-private.csv");
    clearSession();
    signInAs("acme", "bob");
    expect(history()).toEqual([]);
  });

  it("gives the first user their own history back after another user has been and gone", () => {
    signInAs("acme");
    rememberHistory("acme-payroll.csv");
    clearSession();
    signInAs("globex");
    rememberHistory("globex-orders.csv");
    clearSession();
    signInAs("acme");
    expect(history()).toEqual([{ name: "acme-payroll.csv" }]);
  });

  it("stores nothing when nobody is signed in", () => {
    rememberHistory("anonymous.csv");
    expect(window.localStorage.length).toBe(0);
  });

  it("drops the old unscoped entry, which belongs to an unknown tenant", () => {
    window.localStorage.setItem(
      "csv-migrator:jobs:v1",
      JSON.stringify([{ name: "left-by-someone.csv" }]),
    );
    signInAs("globex");
    expect(history()).toEqual([]);
    expect(window.localStorage.getItem("csv-migrator:jobs:v1")).toBeNull();
  });
});

describe("saved mapping templates", () => {
  it("keeps a user's own templates (the feature)", () => {
    signInAs("acme");
    saveTemplate(template("acme-salary"));
    expect(loadTemplates().map((t) => t.name)).toEqual(["acme-salary"]);
  });

  it("does not show another tenant the previous tenant's templates", () => {
    signInAs("acme");
    saveTemplate(template("acme-salary"));
    clearSession();
    signInAs("globex");
    expect(loadTemplates()).toEqual([]);
  });

  it("deletes only the signed-in user's template", () => {
    signInAs("acme");
    saveTemplate(template("shared-name"));
    clearSession();
    signInAs("globex");
    saveTemplate(template("shared-name"));
    deleteTemplate("shared-name");
    expect(loadTemplates()).toEqual([]);
    clearSession();
    signInAs("acme");
    expect(loadTemplates().map((t) => t.name)).toEqual(["shared-name"]);
  });

  it("saves nothing when nobody is signed in", () => {
    saveTemplate(template("anonymous"));
    expect(window.localStorage.length).toBe(0);
    expect(loadTemplates()).toEqual([]);
  });

  it("drops the old unscoped entry", () => {
    window.localStorage.setItem(
      "csv-migrator:mapping-templates",
      JSON.stringify([template("left-by-someone")]),
    );
    signInAs("globex");
    expect(loadTemplates()).toEqual([]);
    expect(window.localStorage.getItem("csv-migrator:mapping-templates")).toBeNull();
  });
});
