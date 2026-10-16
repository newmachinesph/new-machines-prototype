import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";
import en from "../../../messages/en.json";
import ja from "../../../messages/ja.json";
import { resolveSteps, tourFor, TOURS, type TourName } from "./tours";

// Vitest runs from apps/web, where its config lives.
const SRC = join(process.cwd(), "src");

/** Every source file under src, tests aside. */
function sources(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((d) => {
    const path = join(dir, d.name);
    if (d.isDirectory()) return sources(path);
    return /\.tsx?$/.test(d.name) && !/\.test\.tsx?$/.test(d.name) ? [path] : [];
  });
}

const SHELL = join(SRC, "components", "shell.tsx");

/** The `data-tour` values in the source: written as an attribute anywhere, or as a `tour:` field on one of the shell's
 * nav entries (an `Item`, which NavLink renders as `data-tour`). */
function tourTargets(): Set<string> {
  const found = new Set<string>();
  for (const file of sources(SRC)) {
    const text = readFileSync(file, "utf8");
    for (const m of text.matchAll(/\bdata-tour="([^"]+)"/g)) found.add(m[1]);
    if (file === SHELL) {
      for (const m of text.matchAll(/\{ href: "[^"]+", label: "\w+", icon: \w+[^}]*\btour: "([^"]+)" \}/g))
        found.add(m[1]);
    }
  }
  return found;
}

const NAMES = Object.keys(TOURS) as TourName[];

describe("tour definitions", () => {
  it("names every tour", () => {
    expect([...NAMES].sort()).toEqual(["run", "studio", "welcome"]);
  });

  it("gives every tour four to six steps", () => {
    for (const name of NAMES) {
      expect(TOURS[name].length, name).toBeGreaterThanOrEqual(4);
      expect(TOURS[name].length, name).toBeLessThanOrEqual(6);
    }
  });

  it("targets only data-tour attributes that exist in the source", () => {
    const targets = tourTargets();
    for (const name of NAMES) {
      for (const step of TOURS[name]) {
        const value = /^\[data-tour="([^"]+)"\]$/.exec(step.selector)?.[1];
        expect(value, `${name}.${step.key} selector ${step.selector}`).toBeDefined();
        expect(targets.has(value!), `${name}.${step.key}: no data-tour="${value}" in src`).toBe(true);
        if (step.head) expect(step.head.startsWith(`${step.selector} `), `${name}.${step.key} head`).toBe(true);
      }
    }
  });

  it("finds the shell's nav targets through their entries", () => {
    expect(tourTargets().has("nav-runs")).toBe(true);
    expect(tourTargets().has("account-menu")).toBe(true);
  });

  it("uses each step key once per tour", () => {
    for (const name of NAMES) {
      const keys = TOURS[name].map((s) => s.key);
      expect(new Set(keys).size, name).toBe(keys.length);
    }
  });
});

type Copy = Record<string, Record<string, Record<string, unknown>>>;

describe("tour messages", () => {
  const locales = { en: en.tour as unknown as Copy, ja: ja.tour as unknown as Copy };

  it("has a title and body in English and Japanese for every step", () => {
    for (const [locale, tour] of Object.entries(locales)) {
      for (const name of NAMES) {
        for (const { key } of TOURS[name]) {
          for (const part of ["title", "body"]) {
            const text = tour[name]?.[key]?.[part];
            expect(typeof text === "string" && text.trim().length > 0, `${locale}: tour.${name}.${key}.${part}`).toBe(
              true,
            );
          }
        }
      }
    }
  });

  it("has the card's own labels in both languages", () => {
    for (const [locale, tour] of Object.entries(locales)) {
      for (const key of ["next", "back", "done", "skip", "stepOf", "replay"]) {
        expect(tour.common?.[key], `${locale}: tour.common.${key}`).toEqual(expect.any(String));
      }
    }
  });

  it("names no model vendor and hires no agent", () => {
    const text = JSON.stringify([en.tour, ja.tour]);
    expect(text).not.toMatch(/claude|anthropic|\bjev\b|typesafe|openai|gemini|\bgpt|\bhir(e|ed|ing)\b|雇/i);
  });
});

describe("tourFor", () => {
  it.each([
    ["/app", { name: "welcome", href: "/app" }],
    ["/app/marketplace", { name: "welcome", href: "/app" }],
    ["/app/runs", { name: "welcome", href: "/app" }],
    ["/app/runs/new", { name: "welcome", href: "/app" }],
    ["/app/runs/run_1042/evidence", { name: "run", href: "/app/runs/run_1042" }],
    ["/app/runs/run_1042", { name: "run", href: "/app/runs/run_1042" }],
    ["/app/runs/run_1042/other", { name: "welcome", href: "/app" }],
    ["/studio", { name: "studio", href: "/studio" }],
    ["/studio/packs/new", { name: "studio", href: "/studio" }],
    ["/work", null],
    ["/work/tasks/ht_011", null],
    ["/", null],
    ["/application", null],
  ])("offers the tour for %s", (path, area) => {
    expect(tourFor(path)).toEqual(area);
  });
});

describe("resolveSteps", () => {
  afterEach(() => {
    document.body.innerHTML = "";
    vi.restoreAllMocks();
  });

  /** jsdom has no layout, so an element counts as visible when its client rects are stubbed. */
  function place(value: string, visible: boolean) {
    const el = document.createElement("div");
    el.dataset.tour = value;
    const rects = visible ? [new DOMRect(0, 0, 10, 10)] : [];
    vi.spyOn(el, "getClientRects").mockReturnValue(rects as unknown as DOMRectList);
    document.body.append(el);
  }

  it("points at visible targets, centres hidden nav targets, and drops the rest", () => {
    place("a", true);
    place("b", false);
    place("c", false);
    const steps = resolveSteps([
      { key: "a", selector: '[data-tour="a"]', side: "bottom" },
      { key: "b", selector: '[data-tour="b"]', side: "right", centerWhenHidden: true },
      { key: "c", selector: '[data-tour="c"]', side: "right" },
      { key: "d", selector: '[data-tour="d"]', side: "right", centerWhenHidden: true },
    ]);
    expect(steps).toEqual([
      { key: "a", selector: '[data-tour="a"]', side: "bottom" },
      { key: "b", selector: undefined, side: undefined },
    ]);
  });

  it("points at a tall target's head when the target and the card cannot both show", () => {
    vi.spyOn(window, "innerHeight", "get").mockReturnValue(900);
    for (const [value, height] of [
      ["short", 300],
      ["tall", 1400],
    ] as const) {
      const el = document.createElement("section");
      el.dataset.tour = value;
      el.innerHTML = "<div>Title</div><div>Body</div>";
      vi.spyOn(el, "getClientRects").mockReturnValue([new DOMRect(0, 0, 10, 10)] as unknown as DOMRectList);
      vi.spyOn(el, "getBoundingClientRect").mockReturnValue(new DOMRect(0, 0, 600, height));
      const head = el.firstElementChild!;
      vi.spyOn(head, "getClientRects").mockReturnValue([new DOMRect(0, 0, 10, 10)] as unknown as DOMRectList);
      document.body.append(el);
    }
    const def = (value: string) => ({
      key: value,
      selector: `[data-tour="${value}"]`,
      side: "bottom" as const,
      head: `[data-tour="${value}"] > :first-child`,
    });
    expect(resolveSteps([def("short"), def("tall")]).map((s) => s.selector)).toEqual([
      '[data-tour="short"]',
      '[data-tour="tall"] > :first-child',
    ]);
  });
});
