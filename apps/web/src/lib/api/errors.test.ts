import { describe, expect, it, vi } from "vitest";
import { ApiError, toApiError } from "./errors";

describe("toApiError", () => {
  it("reads problem+json bodies", () => {
    const e = toApiError({ status: 409, code: "CONFLICT", detail: "Already granted.", title: "Conflict" });
    expect(e).toBeInstanceOf(ApiError);
    expect(e).toMatchObject({ status: 409, code: "CONFLICT", detail: "Already granted." });
  });
  it("keeps a problem's located errors", () => {
    const issue = { kind: "input", key: "recon", path: "since", message: "'since' is a required property" };
    const e = toApiError({ status: 422, code: "INVALID_INPUT", detail: "The input is not valid.", errors: [issue] });
    expect(e.issues).toEqual([issue]);
    expect(toApiError({ status: 409, code: "CONFLICT", detail: "x", errors: null }).issues).toEqual([]);
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
