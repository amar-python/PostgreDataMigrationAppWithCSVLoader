// #185 (BR-24): the preserved original is the file's bytes, not decoded text.

import { describe, it, expect } from "vitest";
import { bytesToBase64, readFileBase64 } from "@/lib/file-bytes";

function fromBase64(b64: string): Uint8Array {
  return Uint8Array.from(atob(b64), (c) => c.charCodeAt(0));
}

describe("bytesToBase64", () => {
  it("encodes arbitrary bytes, including ones that are not valid UTF-8", () => {
    const bytes = new Uint8Array([0x61, 0x80, 0xff, 0x00, 0x62]);
    expect(Array.from(fromBase64(bytesToBase64(bytes)))).toEqual(Array.from(bytes));
  });

  it("handles input larger than one conversion chunk", () => {
    const bytes = new Uint8Array(0x8000 * 3 + 17).map((_, i) => i % 256);
    expect(fromBase64(bytesToBase64(bytes))).toEqual(bytes);
  });

  it("encodes an empty array as an empty string", () => {
    expect(bytesToBase64(new Uint8Array())).toBe("");
  });
});

describe("readFileBase64", () => {
  it("keeps a UTF-8 BOM that readAsText would drop", async () => {
    const bytes = new Uint8Array([0xef, 0xbb, 0xbf, ...new TextEncoder().encode("a,b\n1,2\n")]);
    const out = fromBase64(await readFileBase64(new File([bytes], "bom.csv")));
    expect(Array.from(out.subarray(0, 3))).toEqual([0xef, 0xbb, 0xbf]);
    expect(out).toEqual(bytes);
  });

  it("keeps a lone 0x80 byte that readAsText would replace with U+FFFD", async () => {
    const bytes = new Uint8Array([...new TextEncoder().encode("a\n1"), 0x80, 0x0a]);
    expect(fromBase64(await readFileBase64(new File([bytes], "bad.csv")))).toEqual(bytes);
  });
});
