import type { UseQueryResult } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ApiError } from "@/lib/api/errors";
import { QueryState } from "./query-state";

const q = (p: Partial<UseQueryResult<string, Error>>) => p as UseQueryResult<string, Error>;
const render401 = () =>
  render(
    <QueryState
      query={q({
        isPending: false,
        isError: true,
        data: undefined,
        error: new ApiError(401, "AUTHENTICATION_REQUIRED", "Sign in to continue."),
      })}
      skeleton={<p>Loading</p>}
    >
      {(d) => <p>{d}</p>}
    </QueryState>,
  );

describe("QueryState", () => {
  it("keeps rendering stale data when a background refetch fails", () => {
    const query = q({ isPending: false, isError: true, data: "stale", error: new Error("blip") });
    render(
      <QueryState query={query} skeleton={<p>Loading</p>}>
        {(d) => <p>{d}</p>}
      </QueryState>,
    );
    expect(screen.getByText("stale")).toBeInTheDocument();
  });

  it("throws when the query failed and there is no data", () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    const query = q({ isPending: false, isError: true, data: undefined, error: new Error("down") });
    expect(() =>
      render(
        <QueryState query={query} skeleton={<p>Loading</p>}>
          {(d) => <p>{d}</p>}
        </QueryState>,
      ),
    ).toThrow("down");
  });

  it("keeps the skeleton on a 401 while the sign-out redirect is pending", () => {
    render401();
    expect(screen.getByText("Loading")).toBeInTheDocument();
    expect(screen.queryByText("Sign in to continue.")).not.toBeInTheDocument();
  });

  it("still throws other API errors", () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    const query = q({ isPending: false, isError: true, data: undefined, error: new ApiError(403, "X", "nope") });
    expect(() =>
      render(
        <QueryState query={query} skeleton={<p>Loading</p>}>
          {(d) => <p>{d}</p>}
        </QueryState>,
      ),
    ).toThrow("nope");
  });
});
