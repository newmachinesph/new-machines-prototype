import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { CommandSkeleton } from "./command-view";

/** The skeleton tiles: the children of the first grid. */
const tiles = (container: HTMLElement) => container.querySelector(".grid")?.children.length;

describe("CommandSkeleton", () => {
  it("draws the demo's six tiles", () => {
    const { container } = render(<CommandSkeleton />);
    expect(tiles(container)).toBe(6);
    expect(container.querySelector(".grid")).toHaveClass("xl:grid-cols-6");
  });

  it("draws the live strip's eight tiles in its four-column grid, so nothing shifts on load", () => {
    const { container } = render(<CommandSkeleton live />);
    expect(tiles(container)).toBe(8);
    expect(container.querySelector(".grid")).toHaveClass("xl:grid-cols-4");
  });
});
