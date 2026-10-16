import { renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";
import { IntlWrapper } from "@/test/intl";
import { humanise, useCodes, useWho } from "./run-codes";

const me = vi.hoisted(() => ({ userId: "pwGlMEou0WQsM6aQvlgggXtXa5C3" }));
vi.mock("@/lib/queries/me", () => ({ useMe: () => ({ data: me }) }));

const wrapper = ({ children }: { children: ReactNode }) => <IntlWrapper>{children}</IntlWrapper>;
const ja = ({ children }: { children: ReactNode }) => <IntlWrapper locale="ja">{children}</IntlWrapper>;

describe("humanise", () => {
  it("turns a code into words", () => {
    expect(humanise("MISMATCHES_FOUND")).toBe("Mismatches found");
    expect(humanise("X")).toBe("X");
  });
});

describe("useCodes", () => {
  it("gives a known code its sentence and an unknown one its words", () => {
    const { result } = renderHook(() => useCodes(), { wrapper });
    expect(result.current.code("ACTION_CLASS_PERMITTED")).toBe("Allowed: your policies permit this kind of action");
    expect(result.current.code("SOME_NEW_CODE")).toBe("Some new code");
  });

  it("rewrites a line written in codes, and leaves prose alone", () => {
    const { result } = renderHook(() => useCodes(), { wrapper });
    const { line } = result.current;
    expect(line("HUMAN_REVIEW: MISMATCHES_FOUND")).toBe("Needs a person: Some orders and payments do not match");
    expect(line("Reason code: MISMATCHES_FOUND")).toBe("Reason: Some orders and payments do not match");
    expect(line("ACTION_CLASS_PERMITTED")).toBe("Allowed: your policies permit this kind of action");
    expect(line("REFERENCE_MISMATCH, AMOUNT_DELTA")).toBe("A reference does not match; The amounts differ");
    expect(line("APPROVED")).toBe("Approved");
    expect(line("Returned 12 records.")).toBe("Returned 12 records.");
    expect(line("USD")).toBe("USD");
    expect(line("Finished: Verify the result")).toBe("Finished: Verify the result");
  });

  it("replaces a model vendor with 'the AI model' in text the API sent, keeping sentences natural", () => {
    const { result } = renderHook(() => useCodes(), { wrapper });
    const { line, subtitle } = result.current;
    expect(line("Rules and Gemini agree. Reason codes: amount delta.")).toBe(
      "Rules and the AI model agree. Reason codes: amount delta.",
    );
    expect(line("Rules pass. Gemini approves.")).toBe("Rules pass. The AI model approves.");
    expect(line("Asked GPT-4, OpenAI and anthropic.")).toBe("Asked the AI model, the AI model and the AI model.");
    expect(line("Geminis are twins")).toBe("Geminis are twins");
    expect(subtitle({ type: "decision", subtitle: "Rules, then Gemini" })).toBe("Rules, then the AI model");
  });

  it("puts the live API's task, version and approval strings in plain words", () => {
    const { result } = renderHook(() => useCodes(), { wrapper });
    const { line, note } = result.current;
    expect(line("Created task ht_run_2011_review_1")).toBe("Created a review task");
    expect(line("Pinned order-payment-reconciliation@2 and order-payment-reconciliation@1")).toBe(
      "Locked the pack and policy versions for this run",
    );
    expect(line("Pinned workflow 1.0.0 and contract 2")).toBe("Pinned workflow 1.0.0 and contract 2");
    expect(note("Waiting on apr_run_2011_approve_write_1.")).toBe("Waiting for approval.");
    expect(note("Waiting on apr_311. Expires 3:00 PM.")).toBe("Waiting for approval. Expires 3:00 PM.");
    expect(note("Retried once.")).toBe("Retried once.");
  });

  it("says in plain words that a run stopped on the monthly cap or its budget, in English and Japanese", () => {
    const en = renderHook(() => useCodes(), { wrapper }).result.current;
    const jp = renderHook(() => useCodes(), { wrapper: ja }).result.current;
    const cap = "SPEND_CAP: A publisher fee of $0.10 for this step would take this month's spend over the cap.";
    const budget = "BUDGET_EXCEEDED: AI spend 312 and publisher fees 20 are over the budget of 300 minor units";
    expect(en.line(cap)).toBe("Stopped: this month's spending cap was reached.");
    expect(en.line(budget)).toBe("Stopped: the run's budget was used up.");
    expect(en.line(`${budget} (NO_ROUTE: draft has no route for 'error')`)).toBe(
      "Stopped: the run's budget was used up.",
    );
    expect(jp.line(cap)).toBe("停止：今月の支出上限に達しました。");
    expect(jp.line(budget)).toBe("停止：この実行の予算を使い切りました。");
  });

  it("drops the code in front of any other failure reason, keeping its sentence", () => {
    const { line } = renderHook(() => useCodes(), { wrapper }).result.current;
    expect(line("NO_ROUTE: draft has no route for 'error'")).toBe("Draft has no route for 'error'");
    expect(line("HUMAN_REVIEW: MISMATCHES_FOUND")).toBe("Needs a person: Some orders and payments do not match");
    expect(line("Note: keep this")).toBe("Note: keep this");
  });

  it("speaks Japanese", () => {
    const { result } = renderHook(() => useCodes(), { wrapper: ja });
    expect(result.current.line("Reason code: ALL_MATCHED")).toBe("理由：すべての注文が入金と一致しました");
  });

  it("puts a step's model profile and access class in plain words", () => {
    const { result } = renderHook(() => useCodes(), { wrapper });
    const { subtitle } = result.current;
    expect(subtitle({ type: "agent", subtitle: "reasoning model" })).toBe("Careful, step-by-step reasoning");
    expect(subtitle({ type: "agent", subtitle: "fast model" })).toBe("Quick, lighter reasoning");
    // The API now writes the profile in sentence case; runs recorded before still say it in lower case.
    expect(subtitle({ type: "agent", subtitle: "Reasoning model" })).toBe("Careful, step-by-step reasoning");
    expect(subtitle({ type: "agent", subtitle: "Fast model" })).toBe("Quick, lighter reasoning");
    expect(subtitle({ type: "connector", subtitle: "read access" })).toBe("Reads only");
    expect(subtitle({ type: "connector", subtitle: "write access" })).toBe("Can make changes");
    expect(subtitle({ type: "human_workforce", subtitle: "Invoice reviewer, $7.50" })).toBe("Invoice reviewer, $7.50");
    expect(subtitle({ type: "agent" })).toBeUndefined();
  });

  it("puts the sample packs' reason codes in words, in English and Japanese", () => {
    const en = renderHook(() => useCodes(), { wrapper }).result.current;
    const jp = renderHook(() => useCodes(), { wrapper: ja }).result.current;
    const codes = {
      DECISION_MODEL_UNAVAILABLE: ["The decision model was not available", "判断モデルを利用できませんでした"],
      LEADS_FOUND: ["Some emails look like real enquiries", "見込み客からの問い合わせと思われるメールがあります"],
      NO_LEADS: ["No email looked like a real enquiry", "見込み客からの問い合わせと思われるメールはありません"],
      EMAILS_SORTED: ["Emails sorted by type", "メールを種類ごとに分類しました"],
      NO_EMAILS: ["No customer emails to answer", "返信が必要な顧客メールはありません"],
      CASES_NEED_A_PERSON: ["Some cases need a person", "担当者の確認が必要なケースがあります"],
      REPLIES_PLANNED: ["Replies planned", "返信を計画しました"],
      NO_EXPENSES: ["No expenses this week", "今週の経費はありません"],
      ODD_ITEMS_FOUND: ["Some expenses look unusual", "通常と異なる経費があります"],
      ALL_ORDINARY: ["Every expense looks ordinary", "すべての経費は通常の範囲です"],
      NO_MEETINGS: ["No meetings need a follow-up", "フォローアップが必要な会議はありません"],
      FOLLOW_UPS_PLANNED: ["Follow-ups planned", "フォローアップを計画しました"],
    };
    for (const [code, [english, japanese]] of Object.entries(codes)) {
      expect(en.code(code)).toBe(english);
      expect(jp.code(code)).toBe(japanese);
    }
  });

  it("puts a decision step's subtitle in words", () => {
    const en = renderHook(() => useCodes(), { wrapper }).result.current;
    const jp = renderHook(() => useCodes(), { wrapper: ja }).result.current;
    expect(en.subtitle({ type: "decision", subtitle: "Rules" })).toBe("Rules");
    expect(en.subtitle({ type: "decision", subtitle: "Decision model" })).toBe("Decision model");
    expect(jp.subtitle({ type: "decision", subtitle: "Rules" })).toBe("ルール");
    expect(jp.subtitle({ type: "decision", subtitle: "Decision model" })).toBe("判断モデル");
  });

  it("never shows the decision model's product or vendor name", () => {
    const { result } = renderHook(() => useCodes(), { wrapper });
    expect(result.current.line("Jev-1.14 answered.")).toBe("The AI model answered.");
    expect(result.current.line("Called OpenRouter and TypeSafe.")).toBe("Called the AI model and the AI model.");
  });
});

describe("useWho", () => {
  it("names the viewer's own account id You, hides anyone else's, and passes names through", () => {
    const { result } = renderHook(() => useWho(), { wrapper });
    expect(result.current(me.userId)).toBe("You");
    expect(result.current("Ab12Cd34Ef56Gh78Ij90Kl12Mn34", "buyer")).toBe("A member of your workspace");
    expect(result.current("Reviewer 204")).toBe("Reviewer 204");
    expect(result.current("You")).toBe("You");
  });

  it("names the viewer's own short account id You, never the raw id", () => {
    const saved = me.userId;
    me.userId = "qa_alice";
    try {
      const { result } = renderHook(() => useWho(), { wrapper });
      expect(result.current("qa_alice", "buyer")).toBe("You");
      expect(result.current("qa_alice")).toBe("You");
    } finally {
      me.userId = saved;
    }
  });

  it("calls an unknown account id on a reviewer's line a reviewer, not a member", () => {
    const { result } = renderHook(() => useWho(), { wrapper });
    expect(result.current("Ab12Cd34Ef56Gh78Ij90Kl12Mn34", "human")).toBe("A reviewer");
    expect(result.current(me.userId, "human")).toBe("You");
    expect(result.current("Maya Santos", "human")).toBe("Maya Santos");
  });

  it("never relabels a machine, policy or system name as a person", () => {
    const { result } = renderHook(() => useWho(), { wrapper });
    const id = "Ab12Cd34Ef56Gh78Ij90Kl12Mn34";
    for (const actor of ["machine", "policy", "system"] as const) expect(result.current(id, actor)).toBe(id);
    expect(result.current(me.userId, "system")).toBe(me.userId);
  });

  it("names no model vendor in who", () => {
    const { result } = renderHook(() => useWho(), { wrapper });
    expect(result.current("Rules + Gemini", "machine")).toBe("Rules + the AI model");
  });

  it("leaves a person's name alone even when it matches a model vendor", () => {
    const { result } = renderHook(() => useWho(), { wrapper });
    expect(result.current("Claude Martin", "human")).toBe("Claude Martin");
    expect(result.current("Claude Martin", "buyer")).toBe("Claude Martin");
  });
});
