/*!
 * @license Apache-2.0
 * Adapted from Synergy Codes Workflow Builder,
 * apps/demo/src/app/plugins/undo-redo/stores/use-undo-redo-store.ts
 * (https://github.com/synergycodes/workflowbuilder, commit 4bbe6512f590f5aea90bce0134f9630e8961a594).
 * Copyright 2025-2026 Synergia Pro Sp. z o.o. Licensed under the Apache License, Version 2.0 (see ./LICENSE).
 *
 * Changes from the original: the history is a value passed in and returned, not a global Zustand store, so each
 * open editor has its own; a snapshot is any object (the editor's nodes, edges and pack details) instead of nodes,
 * edges and layout direction; undo and redo take the present snapshot and return the one to restore instead of
 * writing to the diagram store; the analytics call (trackFutureChange) and devtools are removed; takeSnapshot
 * clamps the slice start at 0 (`Math.max(0, ...)`), where the original's negative start while the history was
 * short made `slice` count from the end and capped the history at half its size.
 */

export const DEFAULT_MAX_HISTORY_SIZE = 100;

export type History<S> = {
  past: S[];
  future: S[];
  /** Snapshots taken when a watched change (a drag, a field being typed in) started, by name. */
  watchers: Record<string, S>;
};

export const emptyHistory = <S>(): History<S> => ({ past: [], future: [], watchers: {} });

export function areSnapshotsEqual<S extends object>(previous: S, current: S): boolean {
  const keys = Object.keys(current) as (keyof S)[];
  if (keys.every((key) => previous[key] === current[key])) return true;
  return JSON.stringify(previous) === JSON.stringify(current);
}

// Core of undo/redo: records each state we decide to record, via takeSnapshot or processSnapshotWatching.
export function takeSnapshot<S extends object>(history: History<S>, snapshot: S): History<S> {
  const lastSnapshot = history.past.at(-1);
  if (lastSnapshot && areSnapshotsEqual(lastSnapshot, snapshot)) return history;
  return {
    ...history,
    past: [...history.past.slice(Math.max(0, history.past.length - DEFAULT_MAX_HISTORY_SIZE + 1)), snapshot],
    future: [],
  };
}

// Starts observing a change that takes many updates, such as moving a node around the diagram.
export function startSnapshotWatching<S>(history: History<S>, name: string, present: S): History<S> {
  return { ...history, watchers: { ...history.watchers, [name]: present } };
}

export function stopSnapshotWatching<S>(history: History<S>, name: string): History<S> {
  return {
    ...history,
    watchers: Object.fromEntries(Object.entries(history.watchers).filter(([key]) => key !== name)),
  };
}

// Records the state from when watching started, once, and stops watching.
export function processSnapshotWatching<S extends object>(
  history: History<S>,
  name: string,
  shouldSkip = false,
): History<S> {
  const snapshot = history.watchers[name];
  if (!snapshot || shouldSkip) return history;
  return stopSnapshotWatching(takeSnapshot(history, snapshot), name);
}

export function undo<S>(history: History<S>, present: S): { history: History<S>; restore: S } | null {
  const pastState = history.past.at(-1);
  if (!pastState) return null;
  return {
    history: { ...history, past: history.past.slice(0, -1), future: [...history.future, present] },
    restore: pastState,
  };
}

export function redo<S>(history: History<S>, present: S): { history: History<S>; restore: S } | null {
  const futureState = history.future.at(-1);
  if (!futureState) return null;
  return {
    history: { ...history, past: [...history.past, present], future: history.future.slice(0, -1) },
    restore: futureState,
  };
}
