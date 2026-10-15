import { useState } from "react";

let counter = 0;
const rowId = () => `row-${++counter}`;

const fit = (ids: string[], count: number) =>
  ids.length === count
    ? ids
    : ids.length < count
      ? [...ids, ...Array.from({ length: count - ids.length }, rowId)]
      : ids.slice(0, count);

/**
 * Stable keys for the rows of a list whose items have no id of their own (a decision's rules, an agent's named
 * inputs), so a row that holds state of its own, such as a half-typed name, keeps it when another row is removed.
 * Call `remove(i)` where a row is removed; rows that appear any other way (an add, an undo) get a new id at the end.
 */
export function useRowIds(count: number) {
  const [ids, setIds] = useState<string[]>(() => fit([], count));
  const fitted = fit(ids, count);
  if (fitted !== ids) setIds(fitted);
  const remove = (i: number) => setIds((current) => current.filter((_, j) => j !== i));
  return { ids: fitted, remove };
}
