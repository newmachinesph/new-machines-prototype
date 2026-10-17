import { renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { Locale } from "@/i18n/locales";
import type { Agent, Pack, Run, RunNode, TimelineEvent } from "@/lib/types";
import { IntlWrapper } from "@/test/intl";
import { relabelRun, useLocalisedRun } from "./run-text";

const node = (over: Partial<RunNode>): RunNode =>
  ({ id: "n", type: "agent", label: "", actor: "machine", status: "COMPLETED", x: 0, y: 0, ...over }) as RunNode;
const event = (over: Partial<TimelineEvent>): TimelineEvent => ({
  at: "2026-10-15T02:31:10Z",
  actor: "machine",
  who: "",
  title: "",
  ...over,
});

/** A reconciliation run as the API projects it: steps and the timeline's `who` in English. */
const run = {
  packSlug: "order-payment-reconciliation",
  nodes: [
    node({ id: "start", type: "trigger", label: "Start", actor: "buyer" }),
    node({ id: "orders", type: "connector", label: "Shopify: list orders", version: "shopify@1" }),
    node({ id: "match", label: "Finance agent", version: "finance-agent@3" }),
    node({ id: "check", type: "decision", label: "Do the orders and payments match?" }),
    node({ id: "done", type: "end", label: "Done", actor: "system" }),
  ],
  timeline: [
    event({ actor: "buyer", who: "You", title: "Started the run", nodeId: "start" }),
    event({ actor: "policy", who: "Policy engine", title: "Permitted Shopify: list orders", nodeId: "orders" }),
    event({ who: "Shopify: list orders", title: "Returned 12 records.", nodeId: "orders" }),
    event({ who: "Finance agent", title: "Matched 11 of 12 orders.", nodeId: "match" }),
    event({ who: "Decision step", title: "Some do not match.", nodeId: "check" }),
    // A reviewer who happens to be called like the step: a person's line, never the step's.
    event({ actor: "human", who: "Shopify: list orders", title: "Resolved the task", nodeId: "orders" }),
    event({ actor: "system", who: "Workflow engine", title: "Completed the run" }),
  ],
} as unknown as Run;

describe("relabelRun", () => {
  const upper = (n: RunNode) => (n.type === "connector" ? n.label.toUpperCase() : n.label);

  it("relabels the steps and the timeline entries each step wrote in its own name, nothing else", () => {
    const shown = relabelRun(run, upper);
    expect(shown.nodes.map((n) => n.label)).toEqual([
      "Start",
      "SHOPIFY: LIST ORDERS",
      "Finance agent",
      "Do the orders and payments match?",
      "Done",
    ]);
    expect(shown.timeline.map((e) => e.who)).toEqual([
      "You",
      "Policy engine",
      "SHOPIFY: LIST ORDERS",
      "Finance agent",
      "Decision step",
      "Shopify: list orders",
      "Workflow engine",
    ]);
    // The policy's line on the same step keeps its own author.
    expect(shown.timeline[1]!.title).toBe("Permitted Shopify: list orders");
    // The reviewer's line on the same step keeps the person's name: the actor is not the step's.
    expect(shown.timeline[5]!.actor).toBe("human");
  });

  it("returns new objects where a label changes and the same ones where it does not", () => {
    const shown = relabelRun(run, upper);
    expect(shown).not.toBe(run);
    expect(shown.nodes[0]).toBe(run.nodes[0]);
    expect(shown.nodes[1]).not.toBe(run.nodes[1]);
    expect(shown.timeline[0]).toBe(run.timeline[0]);
    expect(run.nodes[1]!.label).toBe("Shopify: list orders");
  });

  it("returns the run itself when nothing changes", () => {
    expect(relabelRun(run, (n) => n.label)).toBe(run);
  });
});

const packs: Pick<Pack, "slug" | "certified">[] = [{ slug: "order-payment-reconciliation", certified: true }];
const catalog = vi.hoisted(() => ({ packs: undefined as unknown, agents: {} as Record<string, unknown> }));
vi.mock("@/lib/queries/catalog", () => ({
  usePacks: () => ({ data: catalog.packs }),
  useAgentById: () => (key: string) => catalog.agents[key],
}));
const finance: Pick<Agent, "id" | "name" | "certified"> = {
  id: "finance-agent",
  name: "Finance Agent",
  certified: true,
};

const localised = (r: Run, locale: Locale) =>
  renderHook(() => useLocalisedRun(r), {
    wrapper: ({ children }) => <IntlWrapper locale={locale}>{children}</IntlWrapper>,
  }).result.current;

describe("useLocalisedRun", () => {
  it("labels our pack's steps and their timeline lines in Japanese, the agent step by its agent's name", () => {
    catalog.packs = packs;
    catalog.agents = { "finance-agent": finance };
    const shown = localised(run, "ja");
    expect(shown.nodes.map((n) => n.label)).toEqual([
      "開始",
      "Shopify：注文の一覧を取得",
      "財務エージェント",
      "注文と入金は一致しているか？",
      "完了",
    ]);
    expect(shown.timeline.map((e) => e.who)).toEqual([
      "You",
      "Policy engine",
      "Shopify：注文の一覧を取得",
      "財務エージェント",
      "Decision step",
      "Shopify: list orders",
      "Workflow engine",
    ]);
    // What the record says stays as recorded.
    expect(shown.timeline.map((e) => e.title)).toEqual(run.timeline.map((e) => e.title));
  });

  it("keeps the English of a step whose recorded label is not the mirror's: an older or edited pack version", () => {
    catalog.packs = packs;
    catalog.agents = {};
    const older = {
      ...run,
      nodes: run.nodes.map((n) => (n.id === "orders" ? { ...n, label: "Shopify: list open orders" } : n)),
      timeline: run.timeline.map((e) =>
        e.who === "Shopify: list orders" && e.actor === "machine" ? { ...e, who: "Shopify: list open orders" } : e,
      ),
    };
    const shown = localised(older, "ja");
    expect(shown.nodes[1]!.label).toBe("Shopify: list open orders");
    expect(shown.timeline[2]!.who).toBe("Shopify: list open orders");
    // The steps whose labels still match read in Japanese.
    expect(shown.nodes[0]!.label).toBe("開始");
    expect(shown.nodes[3]!.label).toBe("注文と入金は一致しているか？");
  });

  it("keeps the record's English in English, apart from the agent's display name", () => {
    catalog.packs = packs;
    catalog.agents = { "finance-agent": finance };
    const shown = localised(run, "en");
    expect(shown.nodes.map((n) => n.label)).toEqual([
      "Start",
      "Shopify: list orders",
      "Finance Agent",
      "Do the orders and payments match?",
      "Done",
    ]);
    expect(shown.timeline[3]!.who).toBe("Finance Agent");
  });

  it("leaves a pack that is not ours, or not yet known, in the record's words", () => {
    catalog.agents = {};
    catalog.packs = [{ slug: "order-payment-reconciliation", certified: false }];
    expect(localised(run, "ja")).toBe(run);
    catalog.packs = undefined;
    expect(localised(run, "ja")).toBe(run);
  });

  it("keeps a step the messages do not name, in a pack they do", () => {
    catalog.packs = packs;
    catalog.agents = {};
    const extra = {
      ...run,
      nodes: [...run.nodes, node({ id: "later", type: "connector", label: "Gmail: send email" })],
    };
    const shown = localised(extra, "ja");
    expect(shown.nodes.at(-1)!.label).toBe("Gmail: send email");
    expect(shown.nodes[0]!.label).toBe("開始");
  });
});
