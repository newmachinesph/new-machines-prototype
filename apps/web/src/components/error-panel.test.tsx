import { QueryClient, QueryClientProvider, useQuery } from "@tanstack/react-query";
import { cleanup, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Component, type ReactNode, useState } from "react";
import { describe, expect, it, vi } from "vitest";
import { ApiError } from "@/lib/api/errors";
import { renderWithIntl } from "@/test/intl";
import { ErrorPanel } from "./error-panel";
import { QueryState } from "./query-state";

function withClient(ui: ReactNode, qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })) {
  return <QueryClientProvider client={qc}>{ui}</QueryClientProvider>;
}

describe("ErrorPanel", () => {
  it("shows the API error detail in an alert", () => {
    const error = new ApiError(0, "UNREACHABLE", "Can't reach New Machines. Check your connection and retry.");
    renderWithIntl(withClient(<ErrorPanel title="This page could not load" error={error} reset={() => {}} />));
    expect(screen.getByRole("alert")).toHaveTextContent("Can't reach New Machines. Check your connection and retry.");
    expect(screen.getByRole("heading", { name: "This page could not load" })).toBeInTheDocument();
  });

  it("translates errors the app raised itself, but not the API's own detail", () => {
    const offline = new ApiError(0, "UNREACHABLE", "Can't reach New Machines. Check your connection and retry.");
    renderWithIntl(withClient(<ErrorPanel title="x" error={offline} reset={() => {}} />), { locale: "ja" });
    expect(screen.getByRole("alert")).toHaveTextContent("New Machines に接続できません");
    expect(screen.getByRole("button", { name: "再試行" })).toBeInTheDocument();
    cleanup();
    renderWithIntl(
      withClient(<ErrorPanel title="x" error={new ApiError(409, "CONFLICT", "Already granted.")} reset={() => {}} />),
      { locale: "ja" },
    );
    expect(screen.getByRole("alert")).toHaveTextContent("Already granted.");
  });

  it("calls reset when Retry is pressed", async () => {
    const reset = vi.fn();
    renderWithIntl(withClient(<ErrorPanel title="Oops" error={new Error("x")} reset={reset} />));
    await userEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(reset).toHaveBeenCalledTimes(1);
  });

  it("links home to the given place", () => {
    renderWithIntl(
      withClient(
        <ErrorPanel
          title="Oops"
          error={new Error("x")}
          reset={() => {}}
          home={{ href: "/work", label: "Back to available tasks" }}
        />,
      ),
    );
    expect(screen.getByRole("link", { name: "Back to available tasks" })).toHaveAttribute("href", "/work");
  });

  it("refetches a failed query after Retry", async () => {
    const fetcher = vi.fn().mockRejectedValueOnce(new Error("down")).mockResolvedValue("loaded");

    // Stands in for Next's error boundary: shows the panel, and reset re-renders the children.
    class Boundary extends Component<{ children: ReactNode }, { error: unknown; attempt: number }> {
      state = { error: null as unknown, attempt: 0 };
      static getDerivedStateFromError(error: unknown) {
        return { error };
      }
      render() {
        if (this.state.error)
          return (
            <ErrorPanel
              title="Failed"
              error={this.state.error}
              reset={() => this.setState((s) => ({ error: null, attempt: s.attempt + 1 }))}
            />
          );
        return this.props.children;
      }
    }
    function Page() {
      const query = useQuery({ queryKey: ["page"], queryFn: fetcher, retry: false });
      return (
        <QueryState query={query} skeleton={<p>Loading</p>}>
          {(d) => <p>{d}</p>}
        </QueryState>
      );
    }
    function App() {
      const [qc] = useState(() => new QueryClient());
      return (
        <QueryClientProvider client={qc}>
          <Boundary>
            <Page />
          </Boundary>
        </QueryClientProvider>
      );
    }
    vi.spyOn(console, "error").mockImplementation(() => {});
    renderWithIntl(<App />);
    await userEvent.click(await screen.findByRole("button", { name: "Retry" }));
    expect(await screen.findByText("loaded")).toBeInTheDocument();
    expect(fetcher).toHaveBeenCalledTimes(2);
  });
});
