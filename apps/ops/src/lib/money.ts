/** The API's ceiling for any money input (minor units), e.g. spend caps and the platform daily AI cap. */
export const MAX_MINOR = 10_000_000;

const DOLLARS = /^\d{1,9}(\.\d{1,2})?$/;

/**
 * Parses an operator-typed dollar amount ("250", "250.1", "250.10") into minor units with integer
 * arithmetic, so 250.10 is exactly 25010. Anything else (hex, exponents, more than two decimals, negatives,
 * thousands separators) is null, as is a value outside 0..max.
 */
export function parseDollarsToMinor(input: string, max = MAX_MINOR): number | null {
  const text = input.trim();
  if (!DOLLARS.test(text)) return null;
  const [whole, cents = ""] = text.split(".");
  const minor = Number(whole) * 100 + Number(cents.padEnd(2, "0"));
  return minor <= max ? minor : null;
}

/** Minor units back into the editable dollar text, e.g. 25010 → "250.10". */
export function minorToDollarsInput(minor: number): string {
  return `${Math.trunc(minor / 100)}.${String(minor % 100).padStart(2, "0")}`;
}

/** The validation message to show next to a dollar field. */
export const DOLLARS_HINT = `Enter dollars with up to two decimals, from $0 to $${(MAX_MINOR / 100).toLocaleString("en-US")}.`;
