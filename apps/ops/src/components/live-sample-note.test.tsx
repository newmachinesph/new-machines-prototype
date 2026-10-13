import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { LiveSampleNote } from "./live-sample-note";
import { PageHeader } from "./ui";

const workspace = vi.hoisted(() => ({ value: "demo" as "demo" | "live" }));
vi.mock("@/lib/queries/ops", () => ({ useOpsWorkspace: () => workspace.value }));

describe("LiveSampleNote", () => {
  beforeEach(() => {
    workspace.value = "demo";
  });

  it("renders nothing in the demo", () => {
    const { container } = render(<LiveSampleNote>Reviewers here are sample data.</LiveSampleNote>);
    expect(container).toBeEmptyDOMElement();
  });

  it("tags the page Sample in the live workspace", () => {
    workspace.value = "live";
    render(<LiveSampleNote>Reviewers here are sample data.</LiveSampleNote>);
    expect(screen.getByText("Sample")).toBeInTheDocument();
    expect(screen.getByText("Reviewers here are sample data.")).toBeInTheDocument();
  });
});

describe("LiveSampleNote under a page heading", () => {
  it("sits after the h1 when passed to PageHeader", () => {
    workspace.value = "live";
    render(<PageHeader title="Ops team" lede="Staff." below={<LiveSampleNote>Sample list.</LiveSampleNote>} />);
    const heading = screen.getByRole("heading", { level: 1, name: "Ops team" });
    const note = screen.getByText("Sample list.");
    expect(heading.compareDocumentPosition(note) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });
});
