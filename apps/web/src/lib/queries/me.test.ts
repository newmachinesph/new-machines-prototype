import type { UseQueryResult } from "@tanstack/react-query";
import { describe, expect, it } from "vitest";
import type { Me } from "@/lib/api/gen/types.gen";
import { byOperation, orgScoped } from "./me";

const result = <T>(over: Partial<UseQueryResult<T, unknown>>) =>
  ({ isPending: true, isError: false, data: undefined, error: null, status: "pending", ...over }) as UseQueryResult<
    T,
    unknown
  >;

describe("orgScoped", () => {
  it("passes the org query through while /v1/me loads or once it has answered", () => {
    const query = result<number>({});
    expect(orgScoped(result<Me>({}), query)).toBe(query);
    expect(orgScoped(result<Me>({ isPending: false, status: "success" }), query)).toBe(query);
  });

  it("reports /v1/me's failure instead of loading forever", () => {
    const failure = new Error("workspace unavailable");
    const scoped = orgScoped(
      result<Me>({ isPending: false, isError: true, error: failure, status: "error" }),
      result<number>({}),
    );
    expect(scoped).toMatchObject({ isPending: false, isError: true, error: failure });
  });
});

describe("byOperation", () => {
  it("matches every cached query of one operation", () => {
    const match = byOperation("listMembers");
    expect(match({ queryKey: [{ _id: "listMembers", path: { org_id: "a" } }] })).toBe(true);
    expect(match({ queryKey: [{ _id: "listTokens" }] })).toBe(false);
    expect(match({ queryKey: ["plain"] })).toBe(false);
  });
});
