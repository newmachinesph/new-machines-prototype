import { describe, expect, it, vi } from "vitest";

vi.mock("@/lib/env", () => ({ env: { NEXT_PUBLIC_API_URL: "http://localhost:8400" } }));

import { handleUnauthorized, setTokenSource, setUnauthorizedHandler } from "./client";
import { client } from "./gen/client.gen";

async function authHeaderFor(baseUrl: string) {
  let header: string | null = null;
  const fetchMock = vi.fn(async (req: Request) => {
    header = req.headers.get("Authorization");
    return new Response("{}", { headers: { "content-type": "application/json" } });
  });
  setTokenSource(async () => "tok");
  await client.get({ url: "/v1/x", baseUrl, fetch: fetchMock as unknown as typeof fetch, throwOnError: false });
  return header;
}

describe("request interceptor", () => {
  it("sends the token to the API origin", async () => {
    expect(await authHeaderFor("http://localhost:8400")).toBe("Bearer tok");
  });

  it("does not send the token to another origin", async () => {
    expect(await authHeaderFor("https://evil.example")).toBeNull();
  });
});

describe("handleUnauthorized", () => {
  it("handles two separate 401s one after the other", async () => {
    const handler = vi.fn(async () => {});
    setUnauthorizedHandler(handler);
    await handleUnauthorized();
    await handleUnauthorized();
    expect(handler).toHaveBeenCalledTimes(2);
    setUnauthorizedHandler(null);
  });

  it("clears the in-flight guard in the no-handler fallback", async () => {
    setUnauthorizedHandler(null);
    const original = window.location;
    const replace = vi.fn();
    Object.defineProperty(window, "location", { configurable: true, value: { ...original, replace } });
    await handleUnauthorized();
    await handleUnauthorized();
    expect(replace).toHaveBeenCalledTimes(2);
    Object.defineProperty(window, "location", { configurable: true, value: original });
  });
});
