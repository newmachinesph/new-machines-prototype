"use client";

import { useLocale, useMessages, useTranslations } from "next-intl";
import { useCallback, useMemo } from "react";
import { DEFAULT_LOCALE, resolveLocale } from "@/i18n/locales";
import type en from "../../messages/en.json";
import type { Agent, Pack } from "./types";

/**
 * Our own packs, agents and memory spaces in the interface language.
 *
 * The API describes them in English (keyword matching and the Studio round-trip depend on it) and the messages
 * carry the same text in each other language under `content`, keyed by pack slug, agent id and memory space key,
 * with English mirroring the definitions. Only first-party content is overlaid: the API's `certified` flag marks
 * the platform's own packs and agents, never the team's or another workspace's listed ones, whatever their slug.
 * An item the messages do not name, and every item in English, shows the API's text.
 */
type Content = typeof en.content;
type PackSlug = keyof Content["packs"];
type AgentId = keyof Content["agents"];
type SpaceKey = keyof Content["memorySpaces"];
type PackField = keyof Content["packs"][PackSlug];

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
const isSpaceKey = (content: Content, value: string): value is SpaceKey =>
  Object.hasOwn(content.memorySpaces, value);

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

type AgentRef = Pick<Agent, "id" | "name"> & Partial<Pick<Agent, "certified" | "summary">>;

/** An agent as it is shown: a first-party agent's name and summary in the interface language, any other as sent. */
export function useAgentText() {
  const { t, content, on } = useOverlay();
  return useCallback(
    <A extends AgentRef>(agent: A): A => {
      if (!on || !agent.certified) return agent;
      const id = agent.id;
      if (!isAgentId(content, id)) return agent;
      return {
        ...agent,
        name: t(`agents.${id}.name`),
        ...("summary" in agent ? { summary: t(`agents.${id}.summary`) } : {}),
      };
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
