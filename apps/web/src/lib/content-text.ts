"use client";

import { useLocale, useMessages, useTranslations } from "next-intl";
import { useCallback, useMemo } from "react";
import { DEFAULT_LOCALE, resolveLocale } from "@/i18n/locales";
import en from "../../messages/en.json";
import type { Agent, MemoryItem, Pack, RunNode } from "./types";

type AgentSkill = Agent["skills"][number];

/**
 * Our own packs, agents (with their skills), memory spaces and seed memories in the interface language.
 *
 * The API describes them in English (keyword matching and the Studio round-trip depend on it) and the messages
 * carry the same text in each other language under `content`, keyed by pack slug, agent id (and skill key),
 * memory space key (and seed text hash), with English mirroring the definitions. Only first-party content is
 * overlaid: the API's `certified` flag marks the platform's own packs and agents, never the team's or another
 * workspace's listed ones, whatever their slug; a seed memory is one the API labels as a definitions seed whose
 * text is a definition's, word for word. An item the messages do not name, and every item in English, shows the
 * API's text.
 */
type Content = typeof en.content;
type PackSlug = keyof Content["packs"];
type AgentId = keyof Content["agents"];
type SpaceKey = keyof Content["memorySpaces"];
type PackField = keyof Content["packs"][PackSlug];
type SkilledAgentId = keyof Content["skills"];
type SeededSpaceKey = keyof Content["seeds"];
type SteppedPackSlug = keyof Content["steps"];
/** `skills.<agent id>.<skill key>`, `seeds.<space key>.<text hash>` and `steps.<pack slug>.<node id>`, each agent's,
 * space's and pack's own keys only. */
type SkillMessageKey = { [I in SkilledAgentId]: `skills.${I}.${keyof Content["skills"][I] & string}` }[SkilledAgentId];
type SeedMessageKey = { [S in SeededSpaceKey]: `seeds.${S}.${keyof Content["seeds"][S] & string}` }[SeededSpaceKey];
type StepMessageKey = { [P in SteppedPackSlug]: `steps.${P}.${keyof Content["steps"][P] & string}` }[SteppedPackSlug];

/** The API's source label for a memory that comes with a memory space's definition (`live_work.SOURCES`). */
export const SEED_SOURCE = "Definitions seed";

/**
 * A seed memory's message key: FNV-1a, 32-bit, over the UTF-16 code units of its exact English text (so the same
 * in the test's Node and in the browser), as eight zero-padded hex digits. The API sends a seed's
 * text and its space's name but no index into the definition, and a definition's seeds are reordered or reworded
 * over time, so the text itself is the stable identity; the hash keeps the English out of the client bundle and
 * `content-messages.test.ts` ties every key back to `definitions/memory`. A reworded seed gets a new key and
 * shows its English until the messages catch up, never a stale translation.
 */
export function seedKey(text: string): string {
  let hash = 0x811c9dc5;
  for (let i = 0; i < text.length; i++) {
    hash ^= text.charCodeAt(i);
    hash = Math.imul(hash, 0x01000193) >>> 0;
  }
  return hash.toString(16).padStart(8, "0");
}

/** Memory items carry their space's name, not its key (MemoryItem.scopeName): the definitions' names, by key. */
export const SPACE_KEYS: Record<string, SpaceKey> = {
  "Customer accounts policies": "customer-accounts",
  "Expense policy": "expense-policy",
  "Order-to-cash policy": "o2c-policy",
  "Retail & Commerce company knowledge": "retail-commerce",
  "Support policies": "support-policies",
};

/** The taxonomy's functions, by the English name the API sends as a pack's category, keyed for translation. */
type CategoryKey = "financeOps" | "customerOps" | "fulfillment" | "merchandising" | "operations" | "salesOps";
const CATEGORY_KEYS: Record<string, CategoryKey | undefined> = {
  "Finance operations": "financeOps",
  "Customer operations": "customerOps",
  Fulfillment: "fulfillment",
  Merchandising: "merchandising",
  Operations: "operations",
  "Sales operations": "salesOps",
};
/** The taxonomy's industries, by id. */
type IndustryKey = "retailCommerce" | "manufacturing" | "mediaContent" | "professionalServices";
const INDUSTRY_KEYS: Record<string, IndustryKey | undefined> = {
  "retail-commerce": "retailCommerce",
  manufacturing: "manufacturing",
  "media-content": "mediaContent",
  "professional-services": "professionalServices",
};

/** English shows the API's words; every other language overlays the messages' where they name the item. */
function useOverlay() {
  const locale = resolveLocale(useLocale());
  const t = useTranslations("content");
  const content: Content = useMessages().content;
  return useMemo(() => ({ t, content, on: locale !== DEFAULT_LOCALE }), [t, content, locale]);
}
// Own keys only: a slug such as "constructor" must never resolve through the prototype chain.
const isPackSlug = (content: Content, value: string): value is PackSlug => Object.hasOwn(content.packs, value);
const isAgentId = (content: Content, value: string): value is AgentId => Object.hasOwn(content.agents, value);
const isSpaceKey = (content: Content, value: string): value is SpaceKey => Object.hasOwn(content.memorySpaces, value);
const isSkilledAgentId = (content: Content, value: string): value is SkilledAgentId =>
  Object.hasOwn(content.skills, value);
const isSeededSpaceKey = (content: Content, value: string): value is SeededSpaceKey =>
  Object.hasOwn(content.seeds, value);
const isSteppedPackSlug = (content: Content, value: string): value is SteppedPackSlug =>
  Object.hasOwn(content.steps, value);

type PackRef = Pick<Pack, "slug" | "name"> &
  Partial<Pick<Pack, "certified" | "outcome" | "description" | "humanReview" | "priceNote">>;

/**
 * A pack as it is shown: a first-party pack's name, outcome, description, human-review line and price note in the
 * interface language, any other pack as the API sent it. Takes the whole pack or a reference to one (an agent's
 * `usedBy` entry, given its agent's `certified`), and gives back the same shape.
 */
export function usePackText() {
  const { t, content, on } = useOverlay();
  return useCallback(
    <P extends PackRef>(pack: P): P => {
      if (!on || !pack.certified) return pack;
      const slug = pack.slug;
      if (!isPackSlug(content, slug)) return pack;
      const text = (field: PackField) => t(`packs.${slug}.${field}`);
      return {
        ...pack,
        name: text("name"),
        ...("outcome" in pack ? { outcome: text("outcome") } : {}),
        ...("description" in pack ? { description: text("description") } : {}),
        ...("humanReview" in pack ? { humanReview: text("humanReview") } : {}),
        // A pack without a price note (the API sends none for a listed pack) keeps none.
        ...(pack.priceNote ? { priceNote: text("priceNote") } : {}),
      };
    },
    [t, content, on],
  );
}

type AgentRef = Pick<Agent, "id" | "name"> & Partial<Pick<Agent, "certified" | "summary" | "skills">>;

/**
 * An agent as it is shown: a first-party agent's name, summary and skill titles in the interface language, any
 * other as sent. Skills are keyed by their file name (AgentSkill.key), so two agents' "Write report" differ.
 */
export function useAgentText() {
  const { t, content, on } = useOverlay();
  return useCallback(
    <A extends AgentRef>(agent: A): A => {
      if (!on || !agent.certified) return agent;
      const id = agent.id;
      if (!isAgentId(content, id)) return agent;
      // The own-key check is the runtime guard; the cast names what it proved.
      const skillTitle = (skill: AgentSkill): AgentSkill =>
        isSkilledAgentId(content, id) && Object.hasOwn(content.skills[id], skill.key)
          ? { ...skill, title: t(`skills.${id}.${skill.key}` as SkillMessageKey) }
          : skill;
      return {
        ...agent,
        name: t(`agents.${id}.name`),
        ...("summary" in agent ? { summary: t(`agents.${id}.summary`) } : {}),
        ...(agent.skills ? { skills: agent.skills.map(skillTitle) } : {}),
      };
    },
    [t, content, on],
  );
}

type SeedRef = Pick<MemoryItem, "text" | "source" | "scopeName">;

/**
 * A memory's text as it is shown: a seed that comes with one of our memory spaces reads in the interface
 * language when its text is the definition's, word for word (see `seedKey`); a team's or a run's memory, a
 * seed reworded since, and every memory in English show the text as stored.
 */
export function useSeedText() {
  const { t, content, on } = useOverlay();
  return useCallback(
    (item: SeedRef): string => {
      if (!on || item.source !== SEED_SOURCE) return item.text;
      const space = Object.hasOwn(SPACE_KEYS, item.scopeName) ? SPACE_KEYS[item.scopeName] : undefined;
      if (space === undefined || !isSeededSpaceKey(content, space)) return item.text;
      const key = seedKey(item.text);
      return Object.hasOwn(content.seeds[space], key) ? t(`seeds.${space}.${key}` as SeedMessageKey) : item.text;
    },
    [t, content, on],
  );
}

type StepPackRef = Pick<Pack, "slug" | "certified">;

/**
 * A workflow step's label in the interface language, for a step of one of our own packs: the run record labels
 * its steps in English (the API's projection of the workflow definition) and the messages carry each first-party
 * pack's steps by node id, with English mirroring the projection (`content-messages.test.ts`). As with a seed
 * memory, the overlay holds only where the record's label is the English mirror, word for word: a run pinned to
 * an older pack version, or to one edited in the console, keeps its own English. Gives `undefined` where the
 * label is not overlaid: in English, for a pack that is not ours or not yet known (`pack` undefined while the
 * catalog loads), for a node the messages do not name (added to the workflow since) and for a label that has
 * moved on, so the caller keeps the record's own words.
 */
export function useStepText() {
  const { t, content, on } = useOverlay();
  return useCallback(
    (pack: StepPackRef | undefined, node: Pick<RunNode, "id" | "label">): string | undefined => {
      if (!on || !pack?.certified) return undefined;
      const slug = pack.slug;
      if (!isSteppedPackSlug(content, slug) || !Object.hasOwn(content.steps[slug], node.id)) return undefined;
      const mirror: Record<string, string> = en.content.steps[slug];
      if (mirror[node.id] !== node.label) return undefined;
      return t(`steps.${slug}.${node.id}` as StepMessageKey);
    },
    [t, content, on],
  );
}

/**
 * A memory space's name as it is shown. The space list carries each space's key (MemorySpaceOption.id); a memory
 * item names its space, so the definitions' English names are known by name. Any other space shows as it is.
 */
export function useSpaceName() {
  const { t, content, on } = useOverlay();
  return useCallback(
    (name: string, key?: string): string => {
      if (!on) return name;
      const known = key ?? (Object.hasOwn(SPACE_KEYS, name) ? SPACE_KEYS[name] : undefined);
      return known !== undefined && isSpaceKey(content, known) ? t(`memorySpaces.${known}`) : name;
    },
    [t, content, on],
  );
}

/** A pack's function (its category) in the interface language; a name the messages do not know shows as it came. */
export function useCategoryName() {
  const t = useTranslations("marketplace.grid");
  return useCallback(
    (name: string): string => {
      const key = CATEGORY_KEYS[name];
      return key ? t(`categories.${key}`) : name;
    },
    [t],
  );
}

/** An industry's name in the interface language, by its id; an id the messages do not know shows its API name. */
export function useIndustryName() {
  const t = useTranslations("marketplace.grid");
  return useCallback(
    (id: string, name: string): string => {
      const key = INDUSTRY_KEYS[id];
      return key ? t(`industries.${key}`) : name;
    },
    [t],
  );
}
