// src/__tests__/mapping-templates.test.ts
// Covers: loadTemplates, saveTemplate, deleteTemplate, findMatchingTemplate, touchTemplate
// All state lives in localStorage, which jsdom provides.

import { describe, it, expect, beforeEach } from "vitest";
import {
  loadTemplates,
  saveTemplate,
  deleteTemplate,
  findMatchingTemplate,
  touchTemplate,
  type MappingTemplate,
} from "@/lib/mapping-templates";

const KEY = "csv-migrator:mapping-templates";

function makeTemplate(id: string, headers: string[]): MappingTemplate {
  return {
    id,
    name: `Template ${id}`,
    columns: headers.map((h) => ({ original: h, renamed: h, type: "text" as const })),
    createdAt: Date.now(),
  };
}

beforeEach(() => {
  localStorage.clear();
});

describe("loadTemplates", () => {
  it("returns an empty array when no templates are stored", () => {
    expect(loadTemplates()).toEqual([]);
  });

  it("returns stored templates", () => {
    const t = makeTemplate("t1", ["a", "b"]);
    localStorage.setItem(KEY, JSON.stringify([t]));
    expect(loadTemplates()).toHaveLength(1);
    expect(loadTemplates()[0].id).toBe("t1");
  });

  it("returns [] when localStorage contains invalid JSON", () => {
    localStorage.setItem(KEY, "not-json{{{");
    expect(loadTemplates()).toEqual([]);
  });
});

describe("saveTemplate", () => {
  it("persists a new template", () => {
    const t = makeTemplate("t1", ["col_a", "col_b"]);
    saveTemplate(t);
    expect(loadTemplates()).toHaveLength(1);
    expect(loadTemplates()[0].id).toBe("t1");
  });

  it("replaces an existing template with the same id", () => {
    const t1 = makeTemplate("t1", ["a"]);
    saveTemplate(t1);
    const t2 = { ...t1, name: "Updated" };
    saveTemplate(t2);
    const all = loadTemplates();
    expect(all).toHaveLength(1);
    expect(all[0].name).toBe("Updated");
  });

  it("prepends the newest template so it appears first", () => {
    saveTemplate(makeTemplate("old", ["x"]));
    saveTemplate(makeTemplate("new", ["y"]));
    expect(loadTemplates()[0].id).toBe("new");
  });
});

describe("deleteTemplate", () => {
  it("removes the template with the matching id", () => {
    saveTemplate(makeTemplate("t1", ["a"]));
    saveTemplate(makeTemplate("t2", ["b"]));
    deleteTemplate("t1");
    const all = loadTemplates();
    expect(all).toHaveLength(1);
    expect(all[0].id).toBe("t2");
  });

  it("is a no-op when the id does not exist", () => {
    saveTemplate(makeTemplate("t1", ["a"]));
    deleteTemplate("does-not-exist");
    expect(loadTemplates()).toHaveLength(1);
  });
});

describe("findMatchingTemplate", () => {
  it("returns null when there are no templates", () => {
    expect(findMatchingTemplate(["a", "b"])).toBeNull();
  });

  it("returns the template whose column originals match in order", () => {
    const t = makeTemplate("t1", ["name", "email"]);
    saveTemplate(t);
    expect(findMatchingTemplate(["name", "email"])?.id).toBe("t1");
  });

  it("returns null when the header set differs", () => {
    saveTemplate(makeTemplate("t1", ["name", "email"]));
    expect(findMatchingTemplate(["name", "phone"])).toBeNull();
  });

  it("returns null when the order differs", () => {
    saveTemplate(makeTemplate("t1", ["a", "b", "c"]));
    expect(findMatchingTemplate(["b", "a", "c"])).toBeNull();
  });
});

describe("touchTemplate", () => {
  it("sets lastUsedAt on the targeted template", () => {
    const t = makeTemplate("t1", ["a"]);
    saveTemplate(t);
    const before = Date.now();
    touchTemplate("t1");
    const updated = loadTemplates().find((x) => x.id === "t1")!;
    expect(updated.lastUsedAt).toBeGreaterThanOrEqual(before);
  });

  it("does not affect other templates", () => {
    saveTemplate(makeTemplate("t1", ["a"]));
    saveTemplate(makeTemplate("t2", ["b"]));
    touchTemplate("t1");
    const t2 = loadTemplates().find((x) => x.id === "t2")!;
    expect(t2.lastUsedAt).toBeUndefined();
  });
});
