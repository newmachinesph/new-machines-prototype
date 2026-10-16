import { useTranslations } from "next-intl";
import { useMe } from "@/lib/queries/me";
import type { Actor, RunNode } from "@/lib/types";

/**
 * The codes the run record carries (policy reason codes, decision reason codes, verdicts), each with a plain
 * sentence in the messages (`run.codes.map`). A code the interface has no sentence for yet reads as words.
 */
const KNOWN_CODES = [
  "ACTION_CLASS_PERMITTED",
  "ACTION_CLASS_DENIED",
  "APPROVAL_GRANTED",
  "APPROVAL_REQUIRED",
  "CAPABILITY_NOT_IN_CONTRACT",
  "CONNECTOR_DISABLED",
  "NOT_CONNECTED",
  "GRANT_REVOKED",
  "ROUTE_CHANGED",
  "UNKNOWN_TOOL",
  "TOOL_NOT_OFFERED",
  "RULES_EVALUATED",
  "PAYMENT_ACTION",
  "MONEY_MOVEMENT_BY_AGENT",
  "MISMATCHES_FOUND",
  "ALL_MATCHED",
  "DATA_MISSING",
  "NO_REQUESTS",
  "CASES_PROPOSED",
  "NOTHING_OVERDUE",
  "REMINDERS_PLANNED",
  "DECISION_MODEL_UNAVAILABLE",
  "LEADS_FOUND",
  "NO_LEADS",
  "EMAILS_SORTED",
  "NO_EMAILS",
  "CASES_NEED_A_PERSON",
  "REPLIES_PLANNED",
  "NO_EXPENSES",
  "ODD_ITEMS_FOUND",
  "ALL_ORDINARY",
  "NO_MEETINGS",
  "FOLLOW_UPS_PLANNED",
  "REFERENCE_MISMATCH",
  "AMOUNT_DELTA",
  "PAYOUT_NOT_FOUND",
  "WITHIN_RETURN_WINDOW",
  "DAMAGE_DESCRIBED",
  "APPROVED",
  "HUMAN_REVIEW",
  "REJECTED",
  "REVISION_REQUIRED",
  "ESCALATED",
  "BLOCKED",
  "ERROR",
  "TIMED_OUT",
  "PASS",
] as const;
type KnownCode = (typeof KNOWN_CODES)[number];
const isKnownCode = (code: string): code is KnownCode => (KNOWN_CODES as readonly string[]).includes(code);

const CODE = "[A-Z][A-Z0-9_]*";
const CODE_LINE = new RegExp(`^(${CODE})(?:: (${CODE}))?$`);
const REASON_LINE = new RegExp(`^Reason code: (${CODE})$`);
const CODE_LIST = new RegExp(`^${CODE}(?:, ${CODE})+$`);
/** Why a run stopped on a cap, as the API records it ("SPEND_CAP: A publisher fee of $0.10 ...", "BUDGET_EXCEEDED:
 * AI spend 312 is over the budget of 300 minor units"): read as one plain sentence each. */
const STOP_LINE = /^(SPEND_CAP|BUDGET_EXCEEDED)\b/;
/** A failure reason the API writes as "CODE: sentence" ("NO_ROUTE: draft has no route for 'error'"). */
const CODE_LEAD = new RegExp(`^(${CODE}): (.+)$`, "s");

/** A code as words, for one the interface has no sentence for: "MISMATCHES_FOUND" reads "Mismatches found". */
export function humanise(code: string): string {
  const words = code.toLowerCase().replace(/_/g, " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}

/** Whether a token is a code (SHOUTING_CASE), not a word: known, or with an underscore in it. */
const isCode = (token: string) => isKnownCode(token) || token.includes("_");

const CREATED_TASK = /^Created task \S+$/;
const PINNED_VERSIONS = /^Pinned \S+@\S+ and \S+@\S+$/;
const WAITING_ON_APPROVAL = /^Waiting on apr_\w+\.?/;
/** A model vendor or product named in text the API sent (whole words, any case; "GPT-4" and "Jev-1.14" count as
 * one). The decision model's product and host names are covered too. */
const VENDOR = /\b(?:gemini|claude|gpt(?:-[\w.]+)?|openai|anthropic|jev(?:-[\w.]+)?|typesafe|openrouter)\b/gi;

/** Plain words for the codes and shorthand the run record carries. */
export function useCodes() {
  const t = useTranslations("run.codes");
  /** Text with any model vendor named as "the AI model"; it starts with a capital where a sentence does. */
  const clean = (text: string): string =>
    text.replace(VENDOR, (match, offset: number) => {
      const generic = t("aiModel");
      return offset === 0 || /[.!?]\s+$/.test(text.slice(0, offset))
        ? generic.charAt(0).toUpperCase() + generic.slice(1)
        : generic;
    });
  const code = (c: string) => (isKnownCode(c) ? t(`map.${c}`) : humanise(c));

  /** A line the run record wrote in codes ("HUMAN_REVIEW: MISMATCHES_FOUND", "Reason code: X", "A, B") in
   * plain words; any other text as it was sent. */
  const line = (text: string): string => {
    const stop = text.match(STOP_LINE);
    if (stop) return t(stop[1] === "SPEND_CAP" ? "stopped.spendCap" : "stopped.budgetExceeded");
    const reason = text.match(REASON_LINE);
    if (reason) return t("reason", { reason: code(reason[1]) });
    const pair = text.match(CODE_LINE);
    if (pair && isCode(pair[1]) && (pair[2] === undefined || isCode(pair[2]))) {
      return pair[2] === undefined ? code(pair[1]) : `${code(pair[1])}: ${code(pair[2])}`;
    }
    if (CODE_LIST.test(text)) {
      const tokens = text.split(", ");
      if (tokens.every(isCode)) return tokens.map(code).join("; ");
    }
    // The code in front of a sentence is for logs; the sentence says it to a person.
    const lead = text.match(CODE_LEAD);
    if (lead && isCode(lead[1]) && !isCode(lead[2])) return clean(lead[2].charAt(0).toUpperCase() + lead[2].slice(1));
    if (CREATED_TASK.test(text)) return t("createdTask");
    if (PINNED_VERSIONS.test(text)) return t("pinnedVersions");
    return clean(text);
  };

  /** A step's note from the run record: "Waiting on apr_9." reads "Waiting for approval."; the id stays in the
   * decision's technical details. */
  const note = (text: string): string =>
    clean(text.replace(WAITING_ON_APPROVAL, (m) => `${t("waitingApproval")}${m.endsWith(".") ? "." : ""}`));

  /** A step's subtitle in plain words: an agent's model profile, a connector's access class. */
  const subtitle = (node: Pick<RunNode, "type" | "subtitle">): string | undefined => {
    const s = node.subtitle;
    if (!s) return undefined;
    if (node.type === "agent") {
      // Any case: runs recorded before the API wrote the profile in sentence case say "reasoning model".
      const profile = s.toLowerCase();
      if (profile === "reasoning model") return t("subtitle.reasoning");
      if (profile === "fast model") return t("subtitle.fast");
    }
    if (node.type === "connector") {
      if (s === "read access") return t("subtitle.read");
      if (s === "write access") return t("subtitle.write");
    }
    if (node.type === "decision") {
      if (s === "Rules") return t("subtitle.rules");
      if (s === "Decision model") return t("subtitle.decisionModel");
    }
    return clean(s);
  };

  return { code, line, note, subtitle, clean };
}

/** What an account id looks like on the wire (a sign-in provider's uid): one long token, no spaces. */
const ID_LIKE = /^[A-Za-z0-9_-]{20,}$/;

/**
 * Who did something, as the viewer should read it. Only a person (the actor `buyer` or `human`) can be an
 * account id: the viewer's own is "You", a workspace member's is unnamed (the member list carries no ids to
 * match it against) and a reviewer's is "A reviewer". A person's name passes through as it is (a reviewer may
 * well be called Claude); machine or system names pass through with any model vendor in them named as "the AI
 * model".
 */
export function useWho() {
  const t = useTranslations("run.who");
  const me = useMe();
  const { clean } = useCodes();
  return (who: string, actor?: Actor): string => {
    const person = actor === "buyer" || actor === "human";
    // The viewer's own account id is "You" whatever it looks like (a short dev sign-in's "qa_alice" too).
    if ((actor === undefined || person) && who === me.data?.userId) return t("you");
    if (!ID_LIKE.test(who) || (actor !== undefined && !person)) return person ? who : clean(who);
    if (who === me.data?.userId) return t("you");
    return actor === "human" ? t("reviewer") : t("member");
  };
}
