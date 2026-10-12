/** Matches every cached variant (any filters, any id) of the given operations, for `invalidateQueries`. */
export const byOp = (...ids: string[]) => ({
  predicate: (query: { queryKey: readonly unknown[] }) =>
    ids.includes((query.queryKey[0] as { _id?: string } | undefined)?._id ?? ""),
});

/** Every ops mutation changes the overview's attention queue and appends to the audit log. */
export const OPS_SIDE_EFFECTS = ["opsGetOverview", "opsListAudit"] as const;
