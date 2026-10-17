import { renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { Locale } from "@/i18n/locales";
import { IntlWrapper } from "@/test/intl";
import {
  SEED_SOURCE,
  seedKey,
  useAgentText,
  useCategoryName,
  useIndustryName,
  usePackText,
  useSeedText,
  useSpaceName,
} from "./content-text";

const hook = <T,>(use: () => T, locale: Locale = "ja") =>
  renderHook(use, { wrapper: ({ children }) => <IntlWrapper locale={locale}>{children}</IntlWrapper> }).result.current;

const recon = {
  slug: "order-payment-reconciliation",
  name: "Order & Payment Reconciliation",
  outcome: "Every order matched to a payment, with exceptions reviewed by a person.",
  description: "Reads your orders and payment records.",
  humanReview: "Mismatches go to an invoice reviewer.",
  priceNote: "About $0.60 to $2.40 of AI work per run, plus up to $7.50 of reviewer time.",
  certified: true,
  installed: false,
};

describe("usePackText", () => {
  it("shows a first-party pack in Japanese, keeping what is not text", () => {
    const shown = hook(usePackText)(recon);
    expect(shown.name).toBe("注文と入金の照合");
    expect(shown.outcome).toBe("すべての注文を入金と突き合わせ、例外は人が確認します。");
    expect(shown.description).toMatch(/^注文と入金の記録を読み取り/);
    expect(shown.humanReview).toMatch(/^不一致は請求書レビュアーに送られます/);
    expect(shown.priceNote).toBe(
      "1回の実行あたり約$0.60～$2.40のAIの作業。不一致に人が必要な場合は、レビュアーの時間が最大$7.50加わります。",
    );
    expect(shown.slug).toBe(recon.slug);
    expect(shown.installed).toBe(false);
  });

  it("translates a reference by slug too, when its agent is first-party", () => {
    const ref = { slug: "overdue-invoice-follow-up", name: "Overdue Invoice Follow-up", certified: true };
    expect(hook(usePackText)(ref)).toEqual({ ...ref, name: "期限超過請求書の督促" });
    expect(hook(usePackText)({ ...ref, certified: false }).name).toBe("Overdue Invoice Follow-up");
  });

  it("leaves another workspace's pack with the same slug, and an unknown one, in its own words", () => {
    const listed = { ...recon, certified: false, publisher: "Harbor Cafe" };
    expect(hook(usePackText)(listed)).toBe(listed);
    const team = { ...recon, slug: "org-5c81-recon", name: "Our recon" };
    expect(hook(usePackText)(team)).toBe(team);
  });

  it("shows the API's English in English", () => {
    expect(hook(usePackText, "en")(recon)).toBe(recon);
  });

  it("keeps a missing price note missing", () => {
    const { priceNote, ...noNote } = recon;
    void priceNote;
    expect(hook(usePackText)(noNote)).not.toHaveProperty("priceNote");
  });
});

const finance = {
  id: "finance-agent",
  name: "Finance Agent",
  summary: "Matches each order to the payment that settled it.",
  certified: true,
  publisher: "New Machines Labs",
};

describe("useAgentText", () => {
  it("shows a first-party agent in Japanese", () => {
    const shown = hook(useAgentText)(finance);
    expect(shown.name).toBe("財務エージェント");
    expect(shown.summary).toMatch(/^各注文を決済した入金と突き合わせ/);
    expect(shown.publisher).toBe("New Machines Labs");
  });

  it("leaves a listed, a sample and an unknown agent as sent, and everything in English", () => {
    expect(hook(useAgentText)({ ...finance, certified: false }).name).toBe("Finance Agent");
    expect(hook(useAgentText)({ ...finance, id: "agent_finance", name: "Invoice Agent" }).name).toBe("Invoice Agent");
    expect(hook(useAgentText, "en")(finance)).toBe(finance);
  });

  it("titles a first-party agent's skills by their file name, leaving one the messages do not know", () => {
    const skills = [
      { key: "match-orders", title: "Match orders" },
      { key: "explain-mismatch", title: "Explain mismatch" },
      { key: "new-skill", title: "New skill" },
    ];
    expect(hook(useAgentText)({ ...finance, skills }).skills).toEqual([
      { key: "match-orders", title: "注文の突き合わせ" },
      { key: "explain-mismatch", title: "不一致の説明" },
      { key: "new-skill", title: "New skill" },
    ]);
    // Two agents' "Write report" are two skills.
    const report = {
      id: "ops-agent",
      name: "Ops Agent",
      certified: true,
      skills: [{ key: "write-report", title: "Write report" }],
    };
    expect(hook(useAgentText)(report).skills[0].title).toBe("レポートの作成");
    expect(hook(useAgentText)({ ...report, certified: false }).skills).toBe(report.skills);
    expect(hook(useAgentText, "en")({ ...finance, skills }).skills).toBe(skills);
  });
});

describe("useSeedText", () => {
  const seed = {
    text: "Orders over $500 need a person to confirm before they are reported as matched.",
    source: SEED_SOURCE,
    scopeName: "Retail & Commerce company knowledge",
  };

  it("shows a seed that comes with one of our spaces in Japanese, by its exact text", () => {
    expect(hook(useSeedText)(seed)).toBe("$500を超える注文は、一致として報告する前に担当者の確認が必要です。");
    expect(hook(useSeedText)({ ...seed, scopeName: "Support policies", text: "Spam gets no reply and no case." })).toBe(
      "スパムには返信せず、案件も作成しません。",
    );
  });

  it("shows anything else as stored: a team's or a run's memory, a reworded seed, another space, and English", () => {
    expect(hook(useSeedText)({ ...seed, source: "Your team" })).toBe(seed.text);
    expect(hook(useSeedText)({ ...seed, source: "Run run_2011" })).toBe(seed.text);
    expect(hook(useSeedText)({ ...seed, text: `${seed.text} ` })).toBe(`${seed.text} `);
    expect(hook(useSeedText)({ ...seed, text: "Orders over $500 need a person to confirm." })).toBe(
      "Orders over $500 need a person to confirm.",
    );
    expect(hook(useSeedText)({ ...seed, scopeName: "Expense policy" })).toBe(seed.text);
    expect(hook(useSeedText)({ ...seed, scopeName: "Harbor Cafe house rules" })).toBe(seed.text);
    expect(hook(useSeedText, "en")(seed)).toBe(seed.text);
  });

  it("keys a seed by a stable hash of its text", () => {
    expect(seedKey(seed.text)).toBe("e51a877c");
    expect(seedKey(seed.text)).toMatch(/^[0-9a-f]{8}$/);
    expect(seedKey(`${seed.text} `)).not.toBe(seedKey(seed.text));
    expect(seedKey("")).toBe("811c9dc5");
  });
});

describe("useSpaceName", () => {
  it("names a first-party space by key or by its English name", () => {
    const name = hook(useSpaceName);
    expect(name("Expense policy", "expense-policy")).toBe("経費ポリシー");
    expect(name("Customer accounts policies")).toBe("顧客アカウントのポリシー");
    expect(name("Harbor Cafe house rules", "org-5c81-rules")).toBe("Harbor Cafe house rules");
    expect(name("Harbor Cafe house rules")).toBe("Harbor Cafe house rules");
    expect(hook(useSpaceName, "en")("Expense policy", "expense-policy")).toBe("Expense policy");
  });
});

describe("useCategoryName and useIndustryName", () => {
  it("translate the taxonomy's names and pass others through", () => {
    expect(hook(useCategoryName)("Finance operations")).toBe("財務業務");
    expect(hook(useCategoryName)("Logistics")).toBe("Logistics");
    expect(hook(useCategoryName, "en")("Finance operations")).toBe("Finance operations");
    expect(hook(useIndustryName)("retail-commerce", "Retail & Commerce")).toBe("小売・コマース");
    expect(hook(useIndustryName)("healthcare", "Healthcare")).toBe("Healthcare");
  });
});
