import { screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { RUN_1042 } from "@/data/runs-recon";
import { money } from "@/lib/format";
import type { Run } from "@/lib/types";
import { renderWithIntl } from "@/test/intl";
import { EvidencePage } from "./evidence-page";

const query = vi.hoisted(() => ({ run: undefined as unknown, receipt: undefined as unknown }));
vi.mock("@/lib/queries/runs", () => ({
  useRun: () => ({ isPending: false, isError: false, data: query.run }),
  useReceipt: () => ({ data: query.receipt }),
}));
vi.mock("next/navigation", () => ({ notFound: vi.fn() }));
const me = vi.hoisted(() => ({ userId: "pwGlMEou0WQsM6aQvlgggXtXa5C3" }));
vi.mock("@/lib/queries/me", () => ({ useMe: () => ({ data: me }) }));

const call = (id: string, action: string, actionClass: string) => ({
  id,
  app: "Gmail",
  action,
  capability: actionClass === "read" ? "mail.read" : "mail.write",
  actionClass,
  status: "CONFIRMED" as const,
  policy: "PERMIT" as const,
  detail: action,
  mocked: true,
});

/** A real refund triage run: Gmail read once, two drafts written after the approval, all on sandbox data. */
const drafts: Run = {
  ...RUN_1042,
  id: "run_2001",
  packSlug: "refund-triage",
  title: "Refund Triage",
  contractRef: "refund-triage@1",
  outcome: "Every refund request matched to its order and payment, with a proposed decision and a reply drafted.",
  stages: { executed: "done", verified: "done", accepted: "not_required", settlement: "not_required" },
  stageNotes: undefined,
  nodes: [
    {
      id: "requests",
      type: "connector",
      label: "Gmail: list threads",
      actor: "machine",
      status: "COMPLETED",
      x: 0,
      y: 0,
      toolCalls: [call("tc_1", "list threads", "read")],
    },
    {
      id: "approve",
      type: "approval",
      label: "Save the refund replies as drafts",
      actor: "buyer",
      status: "COMPLETED",
      x: 210,
      y: 0,
    },
    {
      id: "send",
      type: "connector",
      label: "Gmail: create draft",
      actor: "machine",
      status: "COMPLETED",
      x: 420,
      y: 0,
      toolCalls: [call("tc_2", "create draft", "write"), call("tc_3", "create draft", "write")],
    },
  ],
  edges: [
    { from: "requests", to: "approve", taken: true },
    { from: "approve", to: "send", label: "granted", taken: true },
  ],
  deliverable: {
    ...RUN_1042.deliverable!,
    kind: "Email drafts",
    summary: "2 refund replies were drafted, ready for you to check and send. No refund has been issued.",
    rows: [{ label: "Drafts created", value: "2" }],
    limitations: ["Simulated: connector data came from sandbox responses, not a live account."],
    unresolved: [],
    evidence: [],
    items: [
      { label: "ap@example.net — Your refund request for order #1003", detail: "Hello,\n\nOrder number: #1003." },
      { label: "ar@example.net — Your refund request", detail: "Hello,\n\nOrder number: not given." },
    ],
  },
};

describe("EvidencePage", () => {
  it("adds the run's publisher fees to the billable total", () => {
    query.run = drafts;
    const usd = (amountMinor: number) => ({ amountMinor, currency: "USD" as const });
    const fee = { listingId: "lst_1", name: "Tax filing", publisher: "Harbor Cafe", kind: "pack_run" as const };
    query.receipt = { fees: [{ ...fee, quantity: 1, unit: usd(57), amount: usd(57) }] };
    renderWithIntl(<EvidencePage id={drafts.id} />);
    const billable = screen.getByRole("heading", { name: "Why this is billable" }).closest("section") as HTMLElement;
    expect(within(billable).getByText("Publisher fees").parentElement).toHaveTextContent("$0.57");
    const { ai, human, tools } = drafts.spent;
    const total = ai.amountMinor + human.amountMinor + tools.amountMinor + 57;
    expect(within(billable).getByText("Total").parentElement).toHaveTextContent(money(usd(total)));
    query.receipt = undefined;
  });

  it("lists what the run produced when the deliverable has items", () => {
    query.run = drafts;
    renderWithIntl(<EvidencePage id={drafts.id} />);
    expect(screen.getByRole("heading", { name: "What the run produced" })).toBeInTheDocument();
    expect(screen.getByText("2 items")).toBeInTheDocument();
    expect(screen.getByText("ap@example.net — Your refund request for order #1003")).toBeInTheDocument();
    expect(screen.getByText(/Order number: not given\./)).toBeInTheDocument();
    expect(screen.getByText("Drafts created")).toBeInTheDocument();
  });

  it("builds what was permitted, the contract and the basis from the run, not the reconciliation copy", () => {
    query.run = drafts;
    renderWithIntl(<EvidencePage id={drafts.id} />);
    for (const recon of [
      /Google Sheets was read twice/,
      /Filing it to Drive/,
      /every order matched to a payout/,
      /accepted by you/i,
    ])
      expect(screen.queryByText(recon)).not.toBeInTheDocument();
    expect(screen.getByText("Read only, once, on sandbox data.")).toBeInTheDocument();
    expect(screen.getByText("Wrote 2 times, after your approval, on sandbox data.")).toBeInTheDocument();
    expect(screen.getAllByText("Gmail: list threads.")).toHaveLength(1);
    expect(
      screen.getByText("Its writes ran on sandbox data, so nothing outside New Machines was changed."),
    ).toBeInTheDocument();
    expect(screen.getByText(/^Every refund request matched to its order and payment/)).toBeInTheDocument();
    // The contract's version is a technical detail, not part of the sentence.
    expect(screen.getByText("refund-triage@1").closest("details")).not.toBeNull();
    expect(
      screen.getByText(
        "Verified by the independent check. This pack does not ask for your acceptance. Reviewer pay is owed for the review a person did.",
      ),
    ).toBeInTheDocument();
  });

  it("builds the run facts in Japanese", () => {
    query.run = drafts;
    renderWithIntl(<EvidencePage id={drafts.id} />, { locale: "ja" });
    expect(screen.getByText("書き込み、2回（あなたの承認後）、サンドボックスのデータを使用。")).toBeInTheDocument();
    expect(screen.getByText(/このパックでは、あなたの受け入れは求められません。/)).toBeInTheDocument();
    expect(screen.queryByText(/Google Sheetsを読み取り専用で2回/)).not.toBeInTheDocument();
  });

  it("names the items in Japanese", () => {
    query.run = drafts;
    renderWithIntl(<EvidencePage id={drafts.id} />, { locale: "ja" });
    expect(screen.getByRole("heading", { name: "この実行で作成したもの" })).toBeInTheDocument();
    expect(screen.getByText("2件")).toBeInTheDocument();
  });

  it("shows no item list for a deliverable without items", () => {
    query.run = RUN_1042;
    renderWithIntl(<EvidencePage id={RUN_1042.id} />);
    expect(screen.queryByRole("heading", { name: "What the run produced" })).not.toBeInTheDocument();
    expect(screen.getByText("Orders checked")).toBeInTheDocument();
    // The reconciliation page keeps its written copy, word for word.
    expect(RUN_1042.stages.verified).toBe("done");
    expect(screen.getByText(/Google Sheets was read twice, read-only/)).toBeInTheDocument();
    expect(
      screen.getByText(
        "Verified by the independent check and accepted by you. Reviewer pay was owed from the moment the submission was accepted.",
      ),
    ).toBeInTheDocument();
    expect(screen.getByText(/Every order matched to a payout/)).toBeInTheDocument();
  });

  it("keeps the reconciliation basis word for word in Japanese", () => {
    query.run = RUN_1042;
    renderWithIntl(<EvidencePage id={RUN_1042.id} />, { locale: "ja" });
    expect(
      screen.getByText(
        "独立した検証に合格し、あなたが受け入れました。レビュアー報酬は、提出物が受け入れられた時点で発生しています。",
      ),
    ).toBeInTheDocument();
  });

  it("does not say a real reconciliation run was accepted by you when acceptance was not required", () => {
    query.run = { ...RUN_1042, stages: { ...RUN_1042.stages, accepted: "not_required" }, stageNotes: undefined };
    renderWithIntl(<EvidencePage id={RUN_1042.id} />);
    expect(screen.queryByText(/accepted by you/)).not.toBeInTheDocument();
    expect(
      screen.getByText(
        "Verified by the independent check. This pack does not ask for your acceptance. Reviewer pay was owed from the moment the submission was accepted.",
      ),
    ).toBeInTheDocument();
  });

  it("says a run that ended with nothing to do had no independent check", () => {
    const nothing: Run = {
      ...drafts,
      stages: { executed: "done", verified: "not_required", accepted: "not_required", settlement: "not_required" },
      spent: { ...drafts.spent, human: { amountMinor: 0, currency: "USD" } },
      nodes: drafts.nodes.slice(0, 1),
      edges: [],
    };
    query.run = nothing;
    const { unmount } = renderWithIntl(<EvidencePage id={nothing.id} />);
    expect(screen.queryByText(/Verified by the independent check/)).not.toBeInTheDocument();
    expect(
      screen.getByText("This run had no independent check. This pack does not ask for your acceptance."),
    ).toBeInTheDocument();
    unmount();
    renderWithIntl(<EvidencePage id={nothing.id} />, { locale: "ja" });
    expect(
      screen.getByText(
        "この実行では、独立した検証は行われていません。このパックでは、あなたの受け入れは求められません。",
      ),
    ).toBeInTheDocument();
  });

  it("labels partly sandbox calls and a write that never ran, in English and Japanese", () => {
    const send = drafts.nodes[2];
    const mixed: Run = {
      ...drafts,
      nodes: [
        drafts.nodes[0],
        drafts.nodes[1],
        { ...send, toolCalls: [send.toolCalls![0], { ...send.toolCalls![1], mocked: false }] },
        {
          ...send,
          id: "label",
          toolCalls: [
            {
              ...send.toolCalls![0],
              id: "tc_9",
              action: "add label",
              status: "DENIED",
              policy: "DENY",
              mocked: false,
            },
          ],
        },
      ],
    };
    query.run = mixed;
    const { unmount } = renderWithIntl(<EvidencePage id={mixed.id} />);
    expect(screen.getByText("Wrote 2 times, after your approval, partly on sandbox data.")).toBeInTheDocument();
    expect(screen.getByText("Wrote nothing. 1 call was denied or failed.")).toBeInTheDocument();
    unmount();
    renderWithIntl(<EvidencePage id={mixed.id} />, { locale: "ja" });
    expect(
      screen.getByText("書き込み、2回（あなたの承認後）、一部はサンドボックスのデータを使用。"),
    ).toBeInTheDocument();
    expect(screen.getByText("書き込みなし。1件の呼び出しは拒否されたか失敗しました。")).toBeInTheDocument();
  });

  it("leaves reviewer pay out of the reconciliation basis when no reviewer was paid", () => {
    const noReview: Run = {
      ...RUN_1042,
      stages: { ...RUN_1042.stages, accepted: "not_required" },
      stageNotes: undefined,
      spent: { ...RUN_1042.spent, human: { amountMinor: 0, currency: "USD" } },
    };
    query.run = noReview;
    const { unmount } = renderWithIntl(<EvidencePage id={noReview.id} />);
    expect(screen.queryByText(/Reviewer pay was owed/)).not.toBeInTheDocument();
    expect(
      screen.getByText("Verified by the independent check. This pack does not ask for your acceptance."),
    ).toBeInTheDocument();
    unmount();
    renderWithIntl(<EvidencePage id={noReview.id} />, { locale: "ja" });
    expect(screen.queryByText(/レビュアー報酬は、提出物が受け入れられた時点で発生しています/)).not.toBeInTheDocument();
    expect(
      screen.getByText("独立した検証に合格しました。このパックでは、あなたの受け入れは求められません。"),
    ).toBeInTheDocument();
  });

  it.each(["failed", "blocked"] as const)(
    "says acceptance was not given when it %s, in English and Japanese",
    (accepted) => {
      const notGiven: Run = { ...RUN_1042, stages: { ...RUN_1042.stages, accepted }, stageNotes: undefined };
      query.run = notGiven;
      const { unmount } = renderWithIntl(<EvidencePage id={notGiven.id} />);
      expect(screen.queryByText(/does not ask for your acceptance/)).not.toBeInTheDocument();
      expect(
        screen.getByText(
          "Verified by the independent check. Your acceptance was not given. Reviewer pay was owed from the moment the submission was accepted.",
        ),
      ).toBeInTheDocument();
      unmount();
      renderWithIntl(<EvidencePage id={notGiven.id} />, { locale: "ja" });
      expect(
        screen.getByText(
          "独立した検証に合格しました。あなたの受け入れは得られませんでした。レビュアー報酬は、提出物が受け入れられた時点で発生しています。",
        ),
      ).toBeInTheDocument();
    },
  );

  it("names the viewer instead of their account id, writes codes as sentences and money the interface's way", () => {
    const stranger = "Ab12Cd34Ef56Gh78Ij90Kl12Mn34";
    query.run = {
      ...drafts,
      timeline: [
        ...drafts.timeline,
        {
          at: "2026-10-15T02:31:10Z",
          actor: "machine",
          who: "Do the orders and payments match?",
          title: "HUMAN_REVIEW: MISMATCHES_FOUND",
        },
        { at: "2026-10-15T02:33:26Z", actor: "buyer", who: me.userId, title: "Approved" },
        { at: "2026-10-15T02:33:27Z", actor: "buyer", who: stranger, title: "Approved" },
      ],
      deliverable: { ...drafts.deliverable!, rows: [{ label: "Net difference", value: "-70.40 USD" }] },
    };
    renderWithIntl(<EvidencePage id={drafts.id} />);
    expect(screen.getByText(/Needs a person: Some orders and payments do not match/)).toBeInTheDocument();
    expect(screen.queryByText(/HUMAN_REVIEW/)).not.toBeInTheDocument();
    expect(screen.queryByText(me.userId)).not.toBeInTheDocument();
    expect(screen.queryByText(stranger)).not.toBeInTheDocument();
    expect(screen.getByText("A member of your workspace")).toBeInTheDocument();
    expect(screen.getByText("−$70.40")).toBeInTheDocument();
  });

  it("says acceptance was not given on a pack's own basis too", () => {
    query.run = { ...drafts, stages: { ...drafts.stages, accepted: "failed" } };
    renderWithIntl(<EvidencePage id={drafts.id} />);
    expect(
      screen.getByText(
        "Verified by the independent check. Your acceptance was not given. Reviewer pay is owed for the review a person did.",
      ),
    ).toBeInTheDocument();
  });
});
