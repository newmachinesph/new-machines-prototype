import { describe, expect, it } from "vitest";
import { createIdempotencyKeys, isDefiniteRejection } from "./idempotency";

const counter = () => {
  let n = 0;
  return () => `key-${++n}`;
};

describe("createIdempotencyKeys", () => {
  it("reuses the key for the same payload so a retry is safe", () => {
    const keys = createIdempotencyKeys(counter());
    expect(keys.keyFor({ a: 1 })).toBe("key-1");
    expect(keys.keyFor({ a: 1 })).toBe("key-1");
  });

  it("mints a new key when the payload changes", () => {
    const keys = createIdempotencyKeys(counter());
    keys.keyFor({ a: 1 });
    expect(keys.keyFor({ a: 2 })).toBe("key-2");
  });

  it("mints a new key after reset", () => {
    const keys = createIdempotencyKeys(counter());
    keys.keyFor({ a: 1 });
    keys.reset();
    expect(keys.keyFor({ a: 1 })).toBe("key-2");
  });
});

describe("isDefiniteRejection", () => {
  it.each([
    [0, false],
    [403, true],
    [422, true],
    [408, false],
    [429, false],
    [500, false],
    [503, false],
  ])("status %i gives %s", (status, expected) => {
    expect(isDefiniteRejection(status)).toBe(expected);
  });
});
