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
/** A model vendor or product named in text the API sent (whole words, any case; "GPT-4" counts as one). */
const VENDOR = /\b(?:gemini|model|gpt(?:-[\w.]+)?|openai|provider)\b/gi;

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
      if (s === "reasoning model") return t("subtitle.reasoning");
      if (s === "fast model") return t("subtitle.fast");
    }
    if (node.type === "connector") {
      if (s === "read access") return t("subtitle.read");
      if (s === "write access") return t("subtitle.write");
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
 * well be called model); machine or system names pass through with any model vendor in them named as "the AI
 * model".
 */
export function useWho() {
  const t = useTranslations("run.who");
  const me = useMe();
  const { clean } = useCodes();
  return (who: string, actor?: Actor): string => {
    const person = actor === "buyer" || actor === "human";
    if (!ID_LIKE.test(who) || (actor !== undefined && !person)) return person ? who : clean(who);
    if (who === me.data?.userId) return t("you");
    return actor === "human" ? t("reviewer") : t("member");
  };
}
