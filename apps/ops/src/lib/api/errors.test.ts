import { describe, expect, it, vi } from "vitest";
import { ApiError, toApiError } from "./errors";

describe("toApiError", () => {
  it("reads problem+json bodies", () => {
    const e = toApiError({ status: 409, code: "CONFLICT", detail: "Already granted.", title: "Conflict" });
    expect(e).toBeInstanceOf(ApiError);
    expect(e).toMatchObject({ status: 409, code: "CONFLICT", detail: "Already granted." });
  });
  it("keeps the issue list of an invalid definition", () => {
    const issue = { kind: "agent", key: "finance-agent", path: "runtime.max_turns", message: "must be >= 1" };
    const e = toApiError({ status: 422, code: "INVALID_DEFINITION", detail: "1 problem(s)", errors: [issue] });
    expect(e.issues).toEqual([issue]);
    expect(toApiError({ status: 409, code: "NO_CHANGE", detail: "Unchanged.", errors: null }).issues).toEqual([]);
  });
  it("turns network failures into a reachability error", () => {
    expect(toApiError(new TypeError("Failed to fetch"))).toMatchObject({ status: 0, code: "UNREACHABLE" });
  });
  it("names the field in development and stays plain otherwise", () => {
    const zodLike = { name: "ZodError", issues: [{ path: ["runs", 0, "status"], message: "Invalid option" }] };
    vi.stubEnv("NODE_ENV", "development");
    expect(toApiError(zodLike)).toMatchObject({ code: "CONTRACT", detail: "runs.0.status: Invalid option" });
    vi.stubEnv("NODE_ENV", "production");
    expect(toApiError(zodLike).detail).not.toContain("runs.0");
    vi.unstubAllEnvs();
  });
});
