import { money } from "@/lib/format";
import { DOLLARS_HINT, minorToDollarsInput, parseDollarsToMinor } from "@/lib/money";

export type LimitInput = { unit?: string; value?: number };

const WHOLE = /^\d{1,9}$/;

/** The API's ceiling for every guardrail value (GUARDRAIL_MAX_VALUE). */
export const GUARDRAIL_MAX = 10_000_000;

/** The platform daily AI cap is stored in USD minor units but edited in dollars. */
export const isMoneyUnit = (unit?: string) => unit === "usd_minor";

/** "$600.00", "20 runs", "45 minutes". */
export function formatLimit({ unit, value }: LimitInput): string {
  if (value === undefined) return "Not set";
  if (isMoneyUnit(unit)) return money(value);
  return `${new Intl.NumberFormat("en-US").format(value)} ${unit ?? ""}`.trim();
}

/** The number shown in the edit field: dollars for money, the raw value otherwise. */
export function toFieldValue({ unit, value }: LimitInput): string {
  if (value === undefined) return "";
  return isMoneyUnit(unit) ? minorToDollarsInput(value) : String(value);
}

/** Parses the field into the API's unit (minor units for money). Counts and minutes must be whole numbers. */
export function fromFieldValue(unit: string | undefined, text: string): number | null {
  if (isMoneyUnit(unit)) return parseDollarsToMinor(text);
  const t = text.trim();
  if (!WHOLE.test(t)) return null;
  const n = Number(t);
  return n <= GUARDRAIL_MAX ? n : null;
}

/** Label for the field: "USD", or the unit name. */
export const fieldUnitLabel = (unit?: string) => (isMoneyUnit(unit) ? "USD" : (unit ?? ""));

/** The validation message shown next to the field. */
export const fieldHint = (unit?: string) =>
  isMoneyUnit(unit) ? DOLLARS_HINT : `Enter a whole number from 0 to ${GUARDRAIL_MAX.toLocaleString("en-US")}.`;
