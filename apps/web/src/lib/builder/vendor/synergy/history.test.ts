import { describe, expect, it } from "vitest";
import {
  DEFAULT_MAX_HISTORY_SIZE,
  emptyHistory,
  processSnapshotWatching,
  redo,
  startSnapshotWatching,
  takeSnapshot,
  undo,
} from "./history";

type S = { n: number };

describe("undo history (adapted from Synergy Codes Workflow Builder)", () => {
  it("records snapshots, skips a repeat, and clears redo on a new one", () => {
    let h = takeSnapshot(emptyHistory<S>(), { n: 1 });
    h = takeSnapshot(h, { n: 1 });
    expect(h.past).toEqual([{ n: 1 }]);
    const back = undo(h, { n: 2 });
    expect(back?.restore).toEqual({ n: 1 });
    expect(back?.history.future).toEqual([{ n: 2 }]);
    expect(takeSnapshot(back!.history, { n: 3 }).future).toEqual([]);
  });

  it("redoes what was undone", () => {
    const back = undo(takeSnapshot(emptyHistory<S>(), { n: 1 }), { n: 2 });
    const forward = redo(back!.history, { n: 1 });
    expect(forward?.restore).toEqual({ n: 2 });
    expect(forward?.history.past).toEqual([{ n: 1 }]);
    expect(undo(emptyHistory<S>(), { n: 1 })).toBeNull();
  });

  it("records a watched change once, from where it started", () => {
    let h = startSnapshotWatching(emptyHistory<S>(), "drag", { n: 1 });
    h = processSnapshotWatching(h, "drag", true);
    expect(h.past).toEqual([]);
    h = processSnapshotWatching(h, "drag");
    expect(h.past).toEqual([{ n: 1 }]);
    expect(h.watchers).toEqual({});
  });

  it("keeps at most the newest snapshots", () => {
    let h = emptyHistory<S>();
    for (let n = 0; n < DEFAULT_MAX_HISTORY_SIZE + 5; n++) h = takeSnapshot(h, { n });
    expect(h.past).toHaveLength(DEFAULT_MAX_HISTORY_SIZE);
    expect(h.past.at(-1)).toEqual({ n: DEFAULT_MAX_HISTORY_SIZE + 4 });
  });

  it("keeps every snapshot while the history is short", () => {
    let h = emptyHistory<S>();
    for (let n = 0; n < 60; n++) h = takeSnapshot(h, { n });
    expect(h.past).toHaveLength(60);
    expect(h.past[0]).toEqual({ n: 0 });
  });
});
