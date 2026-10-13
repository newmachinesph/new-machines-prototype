import { describe, expect, it } from "vitest";
import {
  definitionHref,
  exportFileName,
  isKind,
  keyProblem,
  mainFileName,
  markdownPathProblem,
  templateFrom,
} from "./definition-logic";

describe("definitionHref", () => {
  it("keeps a schema key's slash as a path segment and adds the version when given", () => {
    expect(definitionHref("agent", "finance-agent")).toBe("/definitions/agent/finance-agent");
    expect(definitionHref("schema", "order-payment-reconciliation/input", 2)).toBe(
      "/definitions/schema/order-payment-reconciliation/input?version=2",
    );
  });
});

describe("isKind", () => {
  it("accepts the registry's kinds only", () => {
    expect(isKind("decision_rules")).toBe(true);
    expect(isKind("agents")).toBe(false);
  });
});

describe("keyProblem", () => {
  it("accepts slugs and schema keys of the form <pack>/<name>", () => {
    expect(keyProblem("agent", "retail-agent")).toBeNull();
    expect(keyProblem("schema", "order-payment-reconciliation/report")).toBeNull();
  });

  it("explains a bad key in plain words", () => {
    expect(keyProblem("agent", "")).toBe("Enter a key.");
    expect(keyProblem("agent", "Retail Agent")).toMatch(/lowercase letters/);
    expect(keyProblem("agent", "a".repeat(65))).toMatch(/lowercase letters/);
    expect(keyProblem("schema", "input")).toMatch(/<pack>\/<name>/);
  });
});

describe("mainFileName", () => {
  it("names the file the definition lives in", () => {
    expect(mainFileName("agent", "finance-agent")).toBe("agent.yaml");
    expect(mainFileName("pack", "p")).toBe("pack.yaml");
    expect(mainFileName("connector", "stripe")).toBe("stripe.yaml");
    expect(mainFileName("models", "default")).toBe("models.yaml");
    expect(mainFileName("schema", "p/input")).toBe("input.json");
  });
});

describe("templateFrom", () => {
  const yaml = [
    "kind: agent",
    "key: finance-agent",
    "agent_id: finance-agent",
    "name: Finance agent",
    "runtime:",
    "  key: finance-agent",
    "  skills:",
    "  - skills/match-orders.md",
  ].join("\n");

  it("swaps the top-level identity fields to the new key and leaves everything else", () => {
    const out = templateFrom(yaml, "finance-agent", "billing-agent");
    expect(out).toContain("key: billing-agent\nagent_id: billing-agent\n");
    expect(out).toContain("name: Finance agent");
    // Nested fields are references, not identity.
    expect(out).toContain("  key: finance-agent");
  });

  it("swaps quoted identity values too", () => {
    expect(templateFrom("key: 'stripe'\nslug: \"stripe\"", "stripe", "adyen")).toBe("key: adyen\nslug: adyen");
  });

  it("names the copy after the original when given its name", () => {
    const out = templateFrom(yaml, "finance-agent", "billing-agent", "Finance agent");
    expect(out).toContain("\nname: Copy of Finance agent\n");
    expect(out).not.toContain("name: Finance agent");
  });

  it("quotes a copied name that would not read back as plain YAML", () => {
    const out = templateFrom('key: a\nname: "Refunds: EU"\n', "a", "b", "Refunds: EU");
    expect(out).toBe('key: b\nname: "Copy of Refunds: EU"\n');
  });

  it("leaves the name alone without one, or when it is a block scalar", () => {
    expect(templateFrom(yaml, "finance-agent", "billing-agent", undefined)).toContain("name: Finance agent");
    expect(templateFrom("key: a\nname: >\n  Long\n", "a", "b", "Long")).toBe("key: b\nname: >\n  Long\n");
  });
});

describe("markdownPathProblem", () => {
  it("allows new skill files only, and not twice", () => {
    expect(markdownPathProblem("skills/explain.md", [])).toBeNull();
    expect(markdownPathProblem("explain.md", [])).toMatch(/skills\/<name>\.md/);
    expect(markdownPathProblem("skills/../x.md", [])).toMatch(/skills\/<name>\.md/);
    expect(markdownPathProblem("skills/explain.md", ["skills/explain.md"])).toMatch(/already/);
  });
});

describe("exportFileName", () => {
  it("flattens the path so the folder can be rebuilt from the name", () => {
    expect(exportFileName("agents/finance-agent/skills/match.md")).toBe("agents__finance-agent__skills__match.md");
  });
});
