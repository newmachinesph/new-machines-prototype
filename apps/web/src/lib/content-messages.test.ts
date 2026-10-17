import { readdirSync, readFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { shortPriceNote } from "@/app/app/marketplace/per-run";
import en from "../../messages/en.json";
import ja from "../../messages/ja.json";
import { SPACE_KEYS } from "./content-text";

/** The platform's definitions (apps/api reads the same files): every first-party pack, agent and memory space. */
const DEFINITIONS = resolve(__dirname, "../../../../definitions");

/**
 * The top-level scalar fields of a definition file: `key: value`, a quoted value, or a `>-` folded block (its
 * indented lines joined with spaces). Enough for names and descriptions; the API's YAML loader is the authority.
 */
function topLevelFields(text: string): Record<string, string> {
  const fields: Record<string, string> = {};
  const lines = text.split("\n");
  for (let i = 0; i < lines.length; i++) {
    const match = /^([a-z_]+):(.*)$/.exec(lines[i]);
    if (!match) continue;
    const [, key, rest] = match;
    const value = rest.trim();
    if (value === ">-") {
      const parts: string[] = [];
      while (i + 1 < lines.length && /^\s+\S/.test(lines[i + 1])) parts.push(lines[++i].trim());
      fields[key] = parts.join(" ");
    } else if (/^".*"$/.test(value)) fields[key] = JSON.parse(value);
    else fields[key] = value;
  }
  return fields;
}

const definition = (...path: string[]) => topLevelFields(readFileSync(join(DEFINITIONS, ...path), "utf8"));
const dirs = (...path: string[]) =>
  readdirSync(join(DEFINITIONS, ...path), { withFileTypes: true })
    .filter((d) => d.isDirectory())
    .map((d) => d.name)
    .sort();

const packs = Object.fromEntries(dirs("packs").map((dir) => [dir, definition("packs", dir, "pack.yaml")]));
const agents = Object.fromEntries(dirs("agents").map((dir) => [dir, definition("agents", dir, "agent.yaml")]));
const spaces = Object.fromEntries(
  readdirSync(join(DEFINITIONS, "memory"))
    .filter((f) => f.endsWith(".yaml"))
    .map((f) => definition("memory", f))
    .map((s) => [s.key, s.name]),
);

type Texts = Record<string, string>;
const translated = (enText: Texts, jaText: Texts | undefined, what: string) => {
  expect(jaText, `${what} has no Japanese`).toBeDefined();
  for (const [field, text] of Object.entries(enText)) {
    expect(jaText?.[field], `${what}.${field} is not translated`).toEqual(expect.any(String));
    expect(jaText?.[field], `${what}.${field} is still English`).not.toBe(text);
  }
};

describe("first-party content messages", () => {
  it("names every pack in definitions/, mirroring its English and translating it", () => {
    expect(Object.keys(en.content.packs).sort()).toEqual(Object.keys(packs));
    for (const [dir, pack] of Object.entries(packs)) {
      expect(pack.slug, dir).toBe(dir);
      const mirror = en.content.packs[dir as keyof typeof en.content.packs];
      expect(mirror, dir).toEqual({
        name: pack.name,
        outcome: pack.outcome,
        description: pack.description,
        humanReview: pack.human_review,
        priceNote: pack.price_note,
      });
      translated(mirror, ja.content.packs[dir as keyof typeof ja.content.packs], `packs.${dir}`);
    }
  });

  it("names every agent in definitions/, mirroring its English and translating it", () => {
    expect(Object.keys(en.content.agents).sort()).toEqual(Object.keys(agents));
    for (const [id, agent] of Object.entries(agents)) {
      const mirror = en.content.agents[id as keyof typeof en.content.agents];
      expect(mirror, id).toEqual({ name: agent.name, summary: agent.summary });
      translated(mirror, ja.content.agents[id as keyof typeof ja.content.agents], `agents.${id}`);
    }
  });

  it("names every memory space in definitions/, by key and by English name", () => {
    expect(en.content.memorySpaces).toEqual(spaces);
    expect(Object.fromEntries(Object.entries(spaces).map(([key, name]) => [name, key]))).toEqual(SPACE_KEYS);
    for (const [key, name] of Object.entries(spaces)) {
      const own = ja.content.memorySpaces[key as keyof typeof ja.content.memorySpaces];
      expect(own, key).toEqual(expect.any(String));
      expect(own, key).not.toBe(name);
    }
  });

  it("writes each Japanese price note so its priced sentence stands alone on a card", () => {
    for (const [slug, pack] of Object.entries(ja.content.packs)) {
      const short = shortPriceNote(pack.priceNote);
      expect(short, slug).toMatch(/\$\d/);
      expect(short, slug).toMatch(/。$/);
      expect(short.length, slug).toBeLessThan(pack.priceNote.length);
    }
  });

  it("never calls an agent hired in Japanese", () => {
    const texts = [
      ...Object.values(ja.content.packs).flatMap((p) => Object.values(p)),
      ...Object.values(ja.content.agents).flatMap((a) => Object.values(a)),
    ];
    for (const text of texts) expect(text).not.toMatch(/採用|雇用/);
  });
});
