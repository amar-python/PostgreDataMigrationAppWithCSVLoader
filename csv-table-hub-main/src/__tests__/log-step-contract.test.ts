// The upload response is validated against a schema. A log step the API emits but the schema does not
// list makes zod reject the WHOLE response, so an import that succeeded on the server is reported as
// "Failed: Unexpected response shape" (what #186 did when it added the header_mapping step).

import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { processingLogSchema } from "@/lib/csv.functions";

const API = join(__dirname, "../../../api");

/** Every step name the loaders pass to _log(logs, "<step>", ...). */
function stepsTheApiEmits(): Set<string> {
  const steps = new Set<string>();
  for (const dir of ["services", "routers"]) {
    for (const file of readdirSync(join(API, dir)).filter((f) => f.endsWith(".py"))) {
      const source = readFileSync(join(API, dir, file), "utf8");
      for (const m of source.matchAll(/_log\(\s*logs,\s*"([a-z_]+)"/g)) steps.add(m[1]);
    }
  }
  return steps;
}

describe("processing log steps", () => {
  it("finds the steps the API emits (guards the scan itself)", () => {
    const steps = stepsTheApiEmits();
    expect(steps.size).toBeGreaterThan(8);
    expect(steps.has("receive")).toBe(true);
  });

  it("the schema accepts every step the API can emit", () => {
    const known = new Set<string>(processingLogSchema.shape.step.options);
    const unknown = [...stepsTheApiEmits()].filter((s) => !known.has(s));
    expect(unknown).toEqual([]);
  });

  it("lists each step once in the source (two fixes for one missing step once left duplicates)", () => {
    // zod collapses duplicate enum values, so the parsed schema can't show them: read the source.
    const source = readFileSync(join(__dirname, "../lib/csv.functions.ts"), "utf8");
    const block = source.slice(source.indexOf("export const processingLogSchema"));
    const steps = [...block.slice(0, block.indexOf("level:")).matchAll(/^\s+"([a-z_]+)",$/gm)].map(
      (m) => m[1],
    );
    expect(steps.length).toBeGreaterThan(10);
    expect(steps.filter((s, i) => steps.indexOf(s) !== i)).toEqual([]);
  });

  it("accepts the header_mapping entry a dynamic upload with a header mapping returns", () => {
    const entry = {
      ts: 1,
      step: "header_mapping",
      level: "info",
      message: "Applied 2 header renames",
    };
    expect(processingLogSchema.safeParse(entry).success).toBe(true);
  });
});
