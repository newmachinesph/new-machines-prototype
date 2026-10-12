import { beforeEach, describe, expect, it } from "vitest";
import { useUi } from "./ui";

const initial = useUi.getState();

describe("useUi", () => {
  beforeEach(() => useUi.setState(initial, true));

  it("starts with the palette and drawer closed", () => {
    const s = useUi.getState();
    expect(s.paletteOpen).toBe(false);
    expect(s.drawerOpen).toBe(false);
  });

  it("opens and closes the palette without touching the drawer", () => {
    useUi.getState().setPaletteOpen(true);
    expect(useUi.getState().paletteOpen).toBe(true);
    expect(useUi.getState().drawerOpen).toBe(false);
    useUi.getState().setPaletteOpen(false);
    expect(useUi.getState().paletteOpen).toBe(false);
  });

  it("opens and closes the drawer without touching the palette", () => {
    useUi.getState().setDrawerOpen(true);
    expect(useUi.getState().drawerOpen).toBe(true);
    expect(useUi.getState().paletteOpen).toBe(false);
    useUi.getState().setDrawerOpen(false);
    expect(useUi.getState().drawerOpen).toBe(false);
  });
});
