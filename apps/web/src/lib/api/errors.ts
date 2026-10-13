/** One located problem in a request, for example a field of a run's input (`path` is slash-separated). */
export type ApiIssue = { kind: string; key: string; path: string; message: string };

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    readonly detail: string,
    readonly issues: ApiIssue[] = [],
  ) {
    super(detail);
    this.name = "ApiError";
  }
}

/** The plain message for unexpected data. The UI shows a translated version of it. */
export const CONTRACT_DETAIL = "New Machines sent data this page did not expect. Reload to try again.";

type ProblemLike = { status: number; code: string; detail: string; errors?: ApiIssue[] | null };
type ZodLike = { name: "ZodError"; issues: { path: (string | number)[]; message: string }[] };

const isProblem = (e: unknown): e is ProblemLike =>
  typeof e === "object" && e !== null && "code" in e && "status" in e && "detail" in e;
const isZod = (e: unknown): e is ZodLike =>
  typeof e === "object" && e !== null && (e as { name?: string }).name === "ZodError";

export function toApiError(e: unknown): ApiError {
  if (e instanceof ApiError) return e;
  if (isProblem(e)) return new ApiError(e.status, e.code, e.detail, Array.isArray(e.errors) ? e.errors : []);
  if (isZod(e)) {
    const first = e.issues[0];
    // The field name helps while developing; users see a plain message.
    const where = process.env.NODE_ENV === "development" && first ? `${first.path.join(".")}: ${first.message}` : null;
    return new ApiError(500, "CONTRACT", where ?? CONTRACT_DETAIL);
  }
  if (e instanceof TypeError)
    return new ApiError(0, "UNREACHABLE", "Can't reach New Machines. Check your connection and retry.");
  return new ApiError(500, "ERROR", "Something went wrong.");
}
