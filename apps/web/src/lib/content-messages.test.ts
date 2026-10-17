import { readdirSync, readFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { shortPriceNote } from "@/app/app/marketplace/per-run";
import en from "../../messages/en.json";
import ja from "../../messages/ja.json";
import { SPACE_KEYS, seedKey } from "./content-text";

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

/**
 * A top-level `name:` block list of single-line plain scalars (`seed_items`), each `  - ` line trimmed. Anything
 * this reader cannot carry word for word (a quoted, block or multi-line scalar, a comment) fails loudly, since the
 * API's YAML loader is the authority and a silently truncated seed would hash to a key no stored item has.
 */
function blockList(text: string, name: string): string[] {
  const items: string[] = [];
  let inside = false;
  for (const line of text.split("\n")) {
    if (new RegExp(`^${name}:\\s*$`).test(line)) inside = true;
    else if (inside && /^\S/.test(line)) break;
    else if (inside && line.trim() !== "") {
      const match = /^\s+-\s+([^"'|>].*)$/.exec(line);
      if (!match) throw new Error(`${name}: unsupported line (quoted, block or continuation): ${line}`);
      if (/\s#/.test(match[1])) throw new Error(`${name}: a comment would be read as text: ${line}`);
      items.push(match[1].trim());
    }
  }
  return items;
}

/** A flow list such as `[finance.collections, orders.read]`; a block list or a missing field fails loudly. */
function flowList(value: string | undefined, what: string): string[] {
  const match = /^\[(.*)\]$/.exec(value ?? "");
  if (!match) throw new Error(`${what}: expected a flow list, got ${JSON.stringify(value)}`);
  return match[1]
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);
}

/**
 * A skill's title as `catalog/agents.skill_title` derives it: the first Markdown heading after the front matter,
 * outside code fences, else the file stem as words ("find-order" -> "Find order").
 */
function skillTitle(stem: string, text: string): string {
  const body = text.replace(/\r\n/g, "\n").replace(/^---\n[\s\S]*?\n---[ \t]*(?:\n|$)/, "");
  let fenced = false;
  for (const line of body.split("\n")) {
    if (/^ {0,3}(```|~~~)/.test(line)) fenced = !fenced;
    else if (!fenced) {
      const heading = /^ {0,3}#{1,6}[ \t]+(.+?)(?:[ \t]+#+)?[ \t]*$/.exec(line);
      if (heading) return heading[1];
    }
  }
  const words = stem
    .split(/[-_\s]+/)
    .filter(Boolean)
    .join(" ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}

const read = (...path: string[]) => readFileSync(join(DEFINITIONS, ...path), "utf8");
const definition = (...path: string[]) => topLevelFields(read(...path));
const dirs = (...path: string[]) =>
  readdirSync(join(DEFINITIONS, ...path), { withFileTypes: true })
    .filter((d) => d.isDirectory())
    .map((d) => d.name)
    .sort();
const files = (suffix: string, ...path: string[]) =>
  readdirSync(join(DEFINITIONS, ...path))
    .filter((f) => f.endsWith(suffix))
    .sort();

const packs = Object.fromEntries(dirs("packs").map((dir) => [dir, definition("packs", dir, "pack.yaml")]));
const agents = Object.fromEntries(dirs("agents").map((dir) => [dir, definition("agents", dir, "agent.yaml")]));
const spaceFiles = files(".yaml", "memory").map((f) => read("memory", f));
const spaces = Object.fromEntries(spaceFiles.map(topLevelFields).map((s) => [s.key, s.name]));
/** Each space's seed texts, in definition order. */
const seedItems = Object.fromEntries(
  spaceFiles.map((text) => [topLevelFields(text).key, blockList(text, "seed_items")]),
);
/** Each space's seeds by the key the client derives from their text. */
const seeds = Object.fromEntries(
  Object.entries(seedItems).map(([key, items]) => [
    key,
    Object.fromEntries(items.map((item) => [seedKey(item), item])),
  ]),
);
/** Each agent's skills by file stem, titled as the API titles them. */
const skills = Object.fromEntries(
  dirs("agents").map((id) => [
    id,
    Object.fromEntries(
      files(".md", "agents", id, "skills").map((f) => {
        const stem = f.replace(/\.md$/, "");
        return [stem, skillTitle(stem, read("agents", id, "skills", f))];
      }),
    ),
  ]),
);
/** Every capability id a first-party agent declares, as the key `useCapabilityLabel` looks up. */
const capabilityKeys = [
  ...new Set(
    Object.entries(agents)
      .flatMap(([id, a]) => {
        const ids = flowList(a.capabilities, `${id} capabilities`);
        if (ids.length === 0) throw new Error(`${id}: no capability parsed`);
        return ids;
      })
      .map((id) => id.replace(/[^A-Za-z0-9]+/g, "_")),
  ),
].sort();

/** The digits (amounts, days, times, percentages) of a rule: a translation keeps every one. */
const numbers = (text: string) => [...text.matchAll(/\d+(?:[.,:]\d+)*/g)].map((m) => m[0]);

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

  it("carries every seed memory in definitions/memory, keyed by its text, mirroring it and translating it", () => {
    expect(en.content.seeds).toEqual(seeds);
    for (const [space, own] of Object.entries(seeds)) {
      const items = Object.entries(own);
      // Every seed has its own key: a hash collision inside a space would make two seeds one.
      expect(items.length, space).toBe(seedItems[space].length);
      expect(items.length, space).toBeGreaterThan(0);
      const jaSpace: Record<string, string> | undefined = ja.content.seeds[space as keyof typeof ja.content.seeds];
      expect(jaSpace, `${space} has no Japanese seeds`).toBeDefined();
      for (const [key, text] of items) {
        const translation = (jaSpace ?? {})[key];
        expect(translation, `${space}.${key}: ${text}`).toEqual(expect.any(String));
        expect(translation, `${space}.${key} is still English`).not.toBe(text);
        // A seed is a rule the agents follow: its amounts, days, times and percentages survive translation.
        for (const n of numbers(text)) expect(translation, `${space}.${key} lost ${n}`).toContain(n);
      }
    }
  });

  it("titles every skill in definitions/agents as the API does, and translates each", () => {
    expect(en.content.skills).toEqual(skills);
    expect(Object.values(skills).flatMap(Object.keys).length).toBeGreaterThan(0);
    for (const [id, own] of Object.entries(skills)) {
      translated(own, ja.content.skills[id as keyof typeof ja.content.skills], `skills.${id}`);
    }
  });

  it("labels every capability a first-party agent declares, in both languages", () => {
    expect(capabilityKeys.length).toBeGreaterThan(0);
    const enLabels: Record<string, string> = en.agents.capability;
    const jaLabels: Record<string, string> = ja.agents.capability;
    for (const key of capabilityKeys) {
      expect(enLabels[key], `agents.capability.${key} has no English label`).toEqual(expect.any(String));
      expect(jaLabels[key], `agents.capability.${key} has no Japanese label`).toEqual(expect.any(String));
      expect(jaLabels[key], `agents.capability.${key} is still English`).not.toBe(enLabels[key]);
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
      ...Object.values(ja.content.skills).flatMap((s) => Object.values(s)),
      ...Object.values(ja.content.seeds).flatMap((s) => Object.values(s)),
    ];
    for (const text of texts) expect(text).not.toMatch(/採用|雇用/);
  });
});
