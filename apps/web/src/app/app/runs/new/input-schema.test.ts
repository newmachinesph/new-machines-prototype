import { describe, expect, it } from "vitest";
import { buildInput, fieldForIssue, humanize, inputFields, validateInput } from "./input-schema";

const RECON = {
  $schema: "https://json-schema.org/draft/2020-12/schema",
  title: "Reconciliation request",
  type: "object",
  additionalProperties: false,
  required: ["since", "until"],
  properties: {
    since: { type: "string", pattern: "^\\d{4}-\\d{2}-\\d{2}$", description: "First day to reconcile." },
    until: { type: "string", pattern: "^\\d{4}-\\d{2}-\\d{2}$", description: "Last day to reconcile." },
  },
};

const RICH = {
  type: "object",
  required: ["region", "range"],
  properties: {
    region: { type: "string", enum: ["us", "jp"], title: "Store region" },
    limit: { type: "integer", default: 50 },
    ratio: { type: "number" },
    dryRun: { type: "boolean", default: true },
    note: { type: "string", pattern: "^[A-Z]" },
    tags: { type: "array", items: { type: "string" } },
    range: {
      type: "object",
      title: "Date range",
      required: ["from"],
      properties: { from: { type: "string", format: "date" }, to: { type: "string", format: "date" } },
    },
  },
};

const messages = {
  required: (label: string) => `Enter ${label}.`,
  number: "number!",
  integer: "integer!",
  date: "date!",
  pattern: "pattern!",
  json: "json!",
};

describe("inputFields", () => {
  it("is null without an object schema, so the form falls back to free text", () => {
    expect(inputFields(undefined)).toBeNull();
    expect(inputFields({ type: "string" })).toBeNull();
  });

  it("reads the reconciliation pack's date range as two required date fields", () => {
    const fields = inputFields(RECON)!;
    expect(fields.map((f) => [f.name, f.kind, f.required, f.label])).toEqual([
      ["since", "date", true, "Since"],
      ["until", "date", true, "Until"],
    ]);
    expect(fields[0].description).toBe("First day to reconcile.");
  });

  it("supports enums, numbers, integers, booleans, patterns, JSON and one level of nesting", () => {
    const fields = inputFields(RICH)!;
    expect(fields.map((f) => [f.name, f.kind, f.required])).toEqual([
      ["region", "enum", true],
      ["limit", "integer", false],
      ["ratio", "number", false],
      ["dryRun", "boolean", false],
      ["note", "string", false],
      ["tags", "json", false],
      ["range.from", "date", true],
      ["range.to", "date", false],
    ]);
    expect(fields[0]).toMatchObject({ label: "Store region", options: ["us", "jp"] });
    expect(fields[1].initial).toBe("50");
    expect(fields[3]).toMatchObject({ label: "Dry run", initial: true });
    expect(fields[6].group).toBe("Date range");
  });
});

describe("validateInput", () => {
  const fields = inputFields(RICH)!;

  it("names each missing required field", () => {
    expect(validateInput(fields, {}, messages)).toEqual({
      region: "Enter Store region.",
      "range.from": "Enter From.",
    });
  });

  it("checks numbers, integers, dates, patterns and JSON", () => {
    const errors = validateInput(
      fields,
      { region: "us", limit: "2.5", ratio: "x", note: "lower", tags: "[", range: { from: "10/06/2026" } },
      messages,
    );
    expect(errors).toEqual({
      limit: "integer!",
      ratio: "number!",
      note: "pattern!",
      tags: "json!",
      "range.from": "date!",
    });
  });
});

describe("buildInput", () => {
  it("sends typed values at their paths and leaves empty optional fields out", () => {
    const fields = inputFields(RICH)!;
    const input = buildInput(fields, {
      region: "jp",
      limit: "20",
      ratio: "",
      dryRun: false,
      note: "",
      tags: '["a"]',
      range: { from: "2026-10-06", to: "" },
    });
    expect(input).toEqual({ region: "jp", limit: 20, dryRun: false, tags: ["a"], range: { from: "2026-10-06" } });
  });
});

describe("helpers", () => {
  it("maps an API issue path to its field", () => {
    const fields = inputFields(RICH)!;
    expect(fieldForIssue(fields, "range/from")?.name).toBe("range.from");
    expect(fieldForIssue(fields, "nowhere")).toBeUndefined();
  });

  it("humanizes keys", () => {
    expect(humanize("order_ids")).toBe("Order ids");
    expect(humanize("orderIds")).toBe("Order ids");
  });
});

// An optional object with a required child: { window?: { start (required), end, strict } }.
const OPTIONAL_GROUP = {
  type: "object",
  properties: {
    label: { type: "string" },
    window: {
      type: "object",
      title: "Window",
      required: ["start"],
      properties: {
        start: { type: "string", format: "date" },
        end: { type: "string", format: "date" },
        strict: { type: "boolean", default: false },
        extra: { type: "object", properties: { from: { type: "string" } } },
      },
    },
  },
};

describe("an optional object with a required field", () => {
  const fields = inputFields(OPTIONAL_GROUP)!;

  it("marks the field required only within its object", () => {
    expect(fields.find((f) => f.name === "window.start")).toMatchObject({
      required: false,
      requiredInGroup: true,
      groupKey: "window",
      groupRequired: false,
    });
  });

  it("asks for nothing while the object is untouched, and leaves it out of the input", () => {
    const untouched = { label: "x", window: { start: "", end: "", strict: false, extra: "" } };
    expect(validateInput(fields, untouched, messages)).toEqual({});
    expect(buildInput(fields, untouched)).toEqual({ label: "x" });
  });

  it("requires the field once any field of the object is filled", () => {
    expect(validateInput(fields, { window: { end: "2026-10-10" } }, messages)).toEqual({
      "window.start": "Enter Start.",
    });
    expect(validateInput(fields, { window: { strict: true } }, messages)).toEqual({
      "window.start": "Enter Start.",
    });
  });

  it("sends the object, booleans included, once it is filled", () => {
    expect(buildInput(fields, { window: { start: "2026-10-01", end: "", strict: false } })).toEqual({
      window: { start: "2026-10-01", strict: false },
    });
  });

  it("always sends a required object, even with nothing filled in", () => {
    const fieldsRequired = inputFields({ ...OPTIONAL_GROUP, required: ["window"] })!;
    expect(fieldsRequired.find((f) => f.name === "window.start")?.required).toBe(true);
    expect(validateInput(fieldsRequired, {}, messages)).toEqual({ "window.start": "Enter Start." });
    expect(buildInput(fieldsRequired, { window: { strict: false } })).toEqual({ window: { strict: false } });
  });
});

describe("fieldForIssue on deeper paths", () => {
  it("lands on the field holding the path, by the longest matching name", () => {
    const fields = inputFields(OPTIONAL_GROUP)!;
    expect(fieldForIssue(fields, "window/extra/from")?.name).toBe("window.extra");
    expect(fieldForIssue(fields, "/window/start")?.name).toBe("window.start");
    expect(fieldForIssue(fields, "window")).toBeUndefined();
  });
});
