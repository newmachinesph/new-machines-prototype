import { describe, expect, it } from "vitest";
import { SIGN_IN_ERRORS } from "@/lib/auth/messages";
import en from "../../messages/en.json";
import ja from "../../messages/ja.json";

const keys = (o: object, p = ""): string[] =>
  Object.entries(o).flatMap(([k, v]) => (typeof v === "object" && v ? keys(v, `${p}${k}.`) : [`${p}${k}`]));
const valueAt = (m: object, key: string) =>
  key.split(".").reduce<unknown>((o, s) => (o as Record<string, unknown>)[s], m);
/** ICU arguments such as {name} or {n, plural, ...} (not the opening of a plural or select branch such as one {run}), and rich-text tags such as <link>, sorted, so the languages can be compared. */
const placeholders = (s: unknown) =>
  [...String(s).matchAll(/(?<!(?:\b(?:zero|one|two|few|many|other)|=\d+)\s*)\{(\w+)\s*[,}]|<\/?(\w+)>/g)]
    .map((m) => (m[1] ? `{${m[1]}}` : `<${m[2]}>`))
    .sort();

describe("messages", () => {
  it("Japanese has every English key", () => {
    const missing = keys(en).filter((k) => !keys(ja).includes(k));
    expect(missing).toEqual([]);
  });
  it("Japanese has no keys English lacks", () => {
    const extra = keys(ja).filter((k) => !keys(en).includes(k));
    expect(extra).toEqual([]);
  });
  it("no empty strings", () => {
    expect(keys(en).length).toBeGreaterThan(200);
    for (const [name, m] of [
      ["en", en],
      ["ja", ja],
    ] as const) {
      const empty = keys(m).filter((k) => valueAt(m, k) === "");
      expect(empty, name).toEqual([]);
    }
  });
  it("both languages use the same placeholders and rich-text tags", () => {
    const differing = keys(en).filter(
      (k) => placeholders(valueAt(en, k)).join() !== placeholders(valueAt(ja, k)).join(),
    );
    expect(differing).toEqual([]);
  });
  it("reads arguments, not the words inside plural branches", () => {
    expect(placeholders("{n, plural, one {a run} other {# runs}} for {name}")).toEqual(["{name}", "{n}"]);
    expect(placeholders("{n, plural, one {run} other {# runs}}")).toEqual(["{n}"]);
    expect(placeholders("{n, plural, =0 {none} one {run for {name}} other {# runs}}")).toEqual(["{name}", "{n}"]);
    expect(placeholders("<link>{id}</link>")).toEqual(["<link>", "<link>", "{id}"]);
  });
  it("has a message for every sign-in error", () => {
    for (const code of SIGN_IN_ERRORS) expect(valueAt(en, `errors.signIn.${code}`), code).toEqual(expect.any(String));
  });
});
