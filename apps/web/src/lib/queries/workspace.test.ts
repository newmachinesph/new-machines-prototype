import { QueryClient } from "@tanstack/react-query";
import { describe, expect, it } from "vitest";
import { optimistic } from "./workspace";

const key = ["items"] as const;

describe("optimistic", () => {
  it("applies the update to cached data at once", async () => {
    const qc = new QueryClient();
    qc.setQueryData<number[]>(key, [1, 2, 3]);
    await optimistic<number[]>(qc, key, (old) => old.filter((n) => n !== 2));
    expect(qc.getQueryData(key)).toEqual([1, 3]);
  });

  it("rollback restores the previous data", async () => {
    const qc = new QueryClient();
    qc.setQueryData<number[]>(key, [1, 2, 3]);
    const rollback = await optimistic<number[]>(qc, key, (old) => old.filter((n) => n !== 2));
    rollback();
    expect(qc.getQueryData(key)).toEqual([1, 2, 3]);
  });

  it("does nothing when nothing is cached yet", async () => {
    const qc = new QueryClient();
    const rollback = await optimistic<number[]>(qc, key, (old) => [...old, 4]);
    expect(qc.getQueryData(key)).toBeUndefined();
    rollback();
    expect(qc.getQueryData(key)).toBeUndefined();
  });
});
