import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";
import { ApiError } from "@/lib/api/errors";
import { ErrorPanel } from "./error-panel";

const withClient = (ui: ReactNode) => (
  <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    {ui}
  </QueryClientProvider>
);

describe("ErrorPanel", () => {
  it("shows the API's own detail in an alert", () => {
    render(
      withClient(
        <ErrorPanel
          title="This page could not load"
          error={new ApiError(403, "OPS_FORBIDDEN", "Not on the ops allowlist.")}
          reset={() => {}}
        />,
      ),
    );
    expect(screen.getByRole("alert")).toHaveTextContent("Not on the ops allowlist.");
    expect(screen.getByRole("heading", { name: "This page could not load" })).toBeInTheDocument();
  });

  it("calls reset when Retry is pressed", async () => {
    const reset = vi.fn();
    render(withClient(<ErrorPanel title="Oops" error={new Error("x")} reset={reset} />));
    expect(screen.getByRole("alert")).toHaveTextContent("Something went wrong.");
    await userEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(reset).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("link", { name: "Go to command center" })).toHaveAttribute("href", "/command");
  });
});
