import { describe, expect, it } from "vitest";
import { midpointOf, pinRoute, roundedPath } from "./routed-edge";

describe("routed edge geometry", () => {
  it("pins the ends to the handles and keeps the first and last segments horizontal", () => {
    const route = [
      { x: 100, y: 50 },
      { x: 120, y: 50 },
      { x: 120, y: 200 },
      { x: 300, y: 200 },
    ];
    expect(pinRoute(route, { x: 103, y: 52 }, { x: 297, y: 198 })).toEqual([
      { x: 103, y: 52 },
      { x: 120, y: 52 },
      { x: 120, y: 198 },
      { x: 297, y: 198 },
    ]);
  });

  it("adds a step when a straight route's handles are at different heights", () => {
    expect(
      pinRoute(
        [
          { x: 0, y: 0 },
          { x: 100, y: 0 },
        ],
        { x: 0, y: 0 },
        { x: 100, y: 10 },
      ),
    ).toEqual([
      { x: 0, y: 0 },
      { x: 50, y: 0 },
      { x: 50, y: 10 },
      { x: 100, y: 10 },
    ]);
  });

  it("rounds each bend without overshooting short segments", () => {
    const d = roundedPath([
      { x: 0, y: 0 },
      { x: 100, y: 0 },
      { x: 100, y: 6 },
      { x: 200, y: 6 },
    ]);
    expect(d).toBe("M 0 0 L 97 0 Q 100 0 100 3 L 100 3 Q 100 6 103 6 L 200 6");
  });

  it("finds the midpoint along the route's length", () => {
    expect(
      midpointOf([
        { x: 0, y: 0 },
        { x: 100, y: 0 },
        { x: 100, y: 100 },
      ]),
    ).toEqual({ x: 100, y: 0 });
  });
});
