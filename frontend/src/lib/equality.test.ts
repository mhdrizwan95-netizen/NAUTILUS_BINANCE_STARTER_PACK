import { describe, expect, it } from "vitest";

import { stableHash } from "./equality";

describe("stableHash", () => {
  it("produces identical hashes for equivalent objects regardless of key order", () => {
    const alpha = {
      b: 1,
      a: {
        x: 2,
        y: [1, 2, { nested: true }],
      },
    };
    const beta = {
      a: {
        y: [1, 2, { nested: true }],
        x: 2,
      },
      b: 1,
    };

    expect(stableHash(alpha)).toBe(stableHash(beta));
  });

  it("distinguishes structurally different values", () => {
    const base = { a: 1, b: [1, 2, 3] };
    const variant = { a: 1, b: [1, 2, 4] };

    expect(stableHash(base)).not.toBe(stableHash(variant));
  });
});
