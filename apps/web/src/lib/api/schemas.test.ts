import { describe, expect, it } from "vitest";
import runs from "../../../../api/app/fixtures/runs.json";
import packs from "../../../../api/app/fixtures/packs.json";
import tasks from "../../../../api/app/fixtures/human_tasks.json";
import { zHumanTask, zPack, zRun } from "./gen/zod.gen";

describe("generated schemas accept the demo data", () => {
  it.each(runs.map((r) => [r.id, r]))("run %s", (_, r) => expect(zRun.safeParse(r).success).toBe(true));
  it.each(packs.map((p) => [p.slug, p]))("pack %s", (_, p) => expect(zPack.safeParse(p).success).toBe(true));
  it.each(tasks.map((t) => [t.id, t]))("task %s", (_, t) => expect(zHumanTask.safeParse(t).success).toBe(true));
});
