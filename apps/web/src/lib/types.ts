// Types come from the API contract (apps/api, generated into ./api/gen). Aliases keep component imports stable.
export type {
  Agent,
  Approval,
  AttentionItem,
  DecisionRecord,
  Deliverable,
  Earning,
  HumanTask,
  LedgerTxn,
  McpToken,
  Member,
  MemoryItem,
  Money,
  Organization,
  Pack,
  Policy,
  RedactedRecord,
  RevokedGrant,
  Run,
  RunEdge,
  RunNode,
  RunSummary,
  TimelineEvent,
  ToolCall,
  TrustPassport,
  Usage,
} from "./api/gen/types.gen";
import type {
  Connection as ApiConnection,
  HumanTask,
  Pack,
  RevokedGrant,
  Run,
  RunNode,
  SubmitReviewRequest,
} from "./api/gen/types.gen";

/**
 * An app connection as the UI reads it: the API may leave `revoked` out (it defaults to `[]` on the wire), and
 * `useConnections` fills it in, so every card can count on the list.
 */
export type Connection = ApiConnection & { revoked: RevokedGrant[] };

/** Who did a piece of work. Drives colour + glyph everywhere. */
export type Actor = "machine" | "human" | "policy" | "system" | "buyer";
export type RunStatus = Run["status"];
export type NodeStatus = RunNode["status"];
export type NodeType = RunNode["type"];
export type HumanTaskState = HumanTask["state"];
export type HumanMode = HumanTask["mode"];
/** The four outcome states the UI must never merge (VERIFICATION_ENGINE.md). */
export type OutcomeStage = keyof Run["stages"];
export type StageState = Run["stages"]["executed"];
export type RiskClass = Pack["riskClass"];
export type DecisionVerdict = NonNullable<RunNode["decision"]>["verdict"];
export type PolicyVerdict = NonNullable<RunNode["decision"]>["policy"]["verdict"];
export type ToolStatus = NonNullable<RunNode["toolCalls"]>[number]["status"];
export type ReviewVerdict = SubmitReviewRequest["verdict"];
