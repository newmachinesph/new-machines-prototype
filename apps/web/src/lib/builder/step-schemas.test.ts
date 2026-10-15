import { describe, expect, it } from "vitest";
import {
  argText,
  coerceArg,
  isClosed,
  parseArgText,
  rangeOf,
  STEP_SCHEMAS,
  undeclaredKeys,
  withArg,
  withDerived,
  withoutBlank,
} from "./step-schemas";
import { PALETTE } from "./test-fixtures";

describe("step settings schemas", () => {
  it("has a schema for every step type, and only decisions use the rules editor", () => {
    expect(Object.keys(STEP_SCHEMAS).sort()).toEqual([
      "agent",
      "approval",
      "connector",
      "decision",
      "end",
      "human_workforce",
      "memory",
      "trigger",
      "verification",
    ]);
    expect(STEP_SCHEMAS.decision.properties).toEqual({});
    expect(STEP_SCHEMAS.connector.properties.args["x-args"]).toBe(true);
  });

  it("bounds a time limit as the API does: whole seconds, from one second to two days", () => {
    const bounds = { type: "integer", minimum: 1, maximum: 172_800 };
    expect(STEP_SCHEMAS.approval.properties.timeout_s).toMatchObject(bounds);
    expect(STEP_SCHEMAS.human_workforce.properties.timeout_s).toMatchObject(bounds);
  });

  it("sets an agent step's output schema from its agent, and clears a tool's arguments when the tool changes", () => {
    const agent = { type: "agent" as const, config: { agent: "writer-agent", output_schema: "shared/drafts" } };
    expect(withDerived(agent, { agent: "collections-agent" }, PALETTE)).toEqual({
      agent: "collections-agent",
      output_schema: "overdue-invoice-follow-up/plan",
    });
    const app = { type: "connector" as const, config: { tool: "gmail.create_draft", args: { subject: "x" } } };
    expect(withDerived(app, { tool: "stripe.list_invoices", args: { subject: "x" } }, PALETTE)).toEqual({
      tool: "stripe.list_invoices",
      args: {},
    });
    expect(withDerived(app, { tool: "gmail.create_draft", args: { subject: "y" } }, PALETTE).args).toEqual({
      subject: "y",
    });
  });

  it("keeps numbers as numbers for number arguments, and expressions as they are", () => {
    expect(coerceArg("50", "integer")).toBe(50);
    expect(coerceArg("=item.count", "integer")).toBe("=item.count");
    expect(coerceArg("true", "boolean")).toBe(true);
    expect(coerceArg("5x", "integer")).toBe("5x");
    // Only text that reads back as the same number is a number: "1." and "1e" are still being typed.
    expect(coerceArg("1.", "integer")).toBe("1.");
    expect(coerceArg("1e", "number")).toBe("1e");
    expect(coerceArg("0.5", "number")).toBe(0.5);
    expect(coerceArg(" 50 ", "integer")).toBe(50);
  });

  it("tells a schema's declared keys from the rest, and a closed schema from an open one", () => {
    expect(undeclaredKeys({ properties: { a: {} } }, { a: 1, b: 2 })).toEqual(["b"]);
    expect(undeclaredKeys({}, { a: 1 })).toEqual(["a"]);
    expect(undeclaredKeys({ properties: {} }, { constructor: 1 })).toEqual(["constructor"]);
    expect(undeclaredKeys({ properties: { a: {} } }, "=input.args")).toEqual([]);
    expect(isClosed({ additionalProperties: false })).toBe(true);
    expect(isClosed({})).toBe(false);
    expect(isClosed({ additionalProperties: { type: "string" } })).toBe(false);
  });

  it("drops empty optional settings", () => {
    expect(withoutBlank({ title: "", for_each: "", tool: "" }, ["tool"])).toEqual({ tool: "" });
  });

  it("sets one argument, dropping a cleared one and an object left empty", () => {
    expect(withArg({ status: "open" }, "limit", 50)).toEqual({ status: "open", limit: 50 });
    expect(withArg({ status: "open", limit: 50 }, "limit", "")).toEqual({ status: "open" });
    expect(withArg({ status: "open", extra: 1 }, "extra", undefined)).toEqual({ status: "open" });
    expect(withArg({ created: { gte: 5 } }, "created", {})).toEqual({});
    expect(withArg({}, "created", { gte: 5 })).toEqual({ created: { gte: 5 } });
  });

  it("reads a list or object argument as an expression or as JSON, and shows it back as text", () => {
    expect(parseArgText('["a", "b"]', "array")).toEqual({ ok: true, value: ["a", "b"] });
    expect(parseArgText('{"gte": 5}', "object")).toEqual({ ok: true, value: { gte: 5 } });
    expect(parseArgText("=nodes.plan.output.rows", "array")).toEqual({ ok: true, value: "=nodes.plan.output.rows" });
    expect(parseArgText("", "array")).toEqual({ ok: true, value: "" });
    expect(parseArgText("nope", "array")).toEqual({ ok: false });
    // The right JSON of the wrong shape is refused too.
    expect(parseArgText('{"gte": 5}', "array")).toEqual({ ok: false });
    expect(parseArgText("[1]", "object")).toEqual({ ok: false });
    expect(argText(["a", "b"])).toBe('["a","b"]');
    expect(argText("=input.rows")).toBe("=input.rows");
    expect(argText(undefined)).toBe("");
    // Never "[object Object]".
    expect(argText({ gte: 5 })).toBe('{"gte":5}');
  });

  it("reads a number argument's range from its schema", () => {
    expect(rangeOf({ type: "integer", minimum: 1, maximum: 100 })).toEqual({ min: 1, max: 100 });
    expect(rangeOf({ type: "integer", minimum: 1 })).toEqual({ min: 1, max: undefined });
    expect(rangeOf({ type: "string" })).toEqual({ min: undefined, max: undefined });
  });
});
