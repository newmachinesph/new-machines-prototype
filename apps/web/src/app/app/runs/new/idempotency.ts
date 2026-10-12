/** A 4xx (other than timeout or throttling) means the server refused the request, so nothing was created. */
export function isDefiniteRejection(status: number): boolean {
  return status >= 400 && status < 500 && status !== 408 && status !== 429;
}

/**
 * One Idempotency-Key per intended submission: the same key while the payload is unchanged
 * (so a retry after a network error or 5xx cannot create a second run), a new key when the
 * payload changes or after the server definitely rejected the request.
 */
export function createIdempotencyKeys(mint: () => string = () => crypto.randomUUID()) {
  let current: { key: string; payload: string } | null = null;
  return {
    keyFor(payload: unknown): string {
      const json = JSON.stringify(payload);
      if (current?.payload !== json) current = { key: mint(), payload: json };
      return current.key;
    },
    reset() {
      current = null;
    },
  };
}
