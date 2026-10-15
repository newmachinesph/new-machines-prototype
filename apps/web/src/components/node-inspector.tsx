import { useTranslations } from "next-intl";
import Link from "next/link";
import { duration } from "@/lib/format";
import { useFormat } from "@/lib/use-format";
import { useViewerTimeZone } from "@/lib/use-viewer-time-zone";
import { useTask } from "@/lib/queries/tasks";
import type { DecisionRecord, PolicyVerdict, RunNode, ToolStatus } from "@/lib/types";
import { useCodes } from "./run-codes";
import { TechnicalDetails } from "./run-disclosures";
import { Skeleton } from "./skeleton";
import { ActorGlyph, ActorLabel, KeyValues, MockTag, NodeStatusPill, Pill } from "./ui";

const POLICY_TONE: Record<PolicyVerdict, "ink" | "blocked" | "human"> = {
  PERMIT: "ink",
  DENY: "blocked",
  REQUIRE_APPROVAL: "human",
};
// Labels: `run.policy.<verdict>`, `run.toolStatus.<status>`, `run.verdict.<verdict>`.
const TOOL_TONE: Record<ToolStatus, "ink" | "blocked" | "human" | "quiet" | "machine"> = {
  PLANNED: "quiet",
  AUTHORIZED: "machine",
  SENT: "machine",
  CONFIRMED: "ink",
  DENIED: "blocked",
  FAILED: "blocked",
  UNCONFIRMED: "human",
  CANCELLED: "quiet",
};

function Block({
  title,
  glyph,
  children,
}: {
  title: string;
  glyph: Parameters<typeof ActorGlyph>[0]["actor"];
  children: React.ReactNode;
}) {
  return (
    <div className="rounded-[10px] border border-rule">
      <div className="flex items-center gap-2 border-b border-rule px-3.5 py-2 text-xs font-medium text-grey-700">
        <ActorGlyph actor={glyph} className="size-2.5" />
        {title}
      </div>
      <div className="px-3.5 py-3 text-sm">{children}</div>
    </div>
  );
}

/** Reason codes as sentences, one per line. */
function Reasons({ codes }: { codes: string[] }) {
  const { code } = useCodes();
  if (codes.length === 0) return null;
  return (
    <ul className="mt-2 space-y-1 text-[13px] leading-snug text-grey-700">
      {codes.map((r) => (
        <li key={r}>{code(r)}</li>
      ))}
    </ul>
  );
}

function DecisionBlocks({ d }: { d: DecisionRecord }) {
  const t = useTranslations("run.inspector");
  const tt = useTranslations("run.technical");
  const { clean } = useCodes();
  const approvalId = d.approval?.id ?? "";
  return (
    <div className="space-y-3">
      <p className="text-xs leading-relaxed text-muted">{t("threeRecords")}</p>
      <Block title={t("evaluatorTitle")} glyph="machine">
        <div className="font-medium">“{d.question}”</div>
        <ol className="mt-2.5 space-y-2">
          {d.chain.map((c, i) => (
            <li key={i} className="flex gap-2.5">
              <span className="tnum mt-px w-4 shrink-0 text-xs text-muted">{i + 1}</span>
              <div>
                <span className="font-medium">
                  {c.kind === "rules" ? t("rules") : c.kind === "gemini" ? t("aiModel") : "Jev"}
                </span>
                <span className="text-muted">{t("chainVerdict", { verdict: t(`verdict.${c.verdict}`) })}</span>
                <div className="text-[13px] leading-snug text-grey-700">{clean(c.note)}</div>
              </div>
            </li>
          ))}
        </ol>
        <div className="mt-3">
          <Pill tone={d.verdict === "APPROVED" ? "ink" : d.verdict === "HUMAN_REVIEW" ? "human" : "blocked"}>
            {t(`verdict.${d.verdict}`)}
          </Pill>
        </div>
        <Reasons codes={d.reasonCodes} />
        <p className="mt-2.5 text-[13px] leading-snug text-grey-700">{clean(d.explanation)}</p>
        <p className="mt-2 text-xs text-muted">{t("noScore")}</p>
      </Block>
      <Block title={t("policyTitle")} glyph="policy">
        <Pill tone={POLICY_TONE[d.policy.verdict]}>{t(`policy.${d.policy.verdict}`)}</Pill>
        <Reasons codes={d.policy.reasonCodes} />
      </Block>
      {d.approval ? (
        <Block title={t("signOffTitle")} glyph="human">
          {d.approval.status === "PENDING" ? (
            <span>
              {t.rich("waitingOn", {
                link: (chunks) => (
                  <Link className="link" href={`/work/tasks/${approvalId}`}>
                    {chunks}
                  </Link>
                ),
              })}
            </span>
          ) : d.approval.status === "GRANTED" ? (
            <span>{t("grantedBy", { by: d.approval.by ?? "" })}</span>
          ) : (
            <span>{t("notRequired")}</span>
          )}
        </Block>
      ) : null}
      <TechnicalDetails
        rows={[
          { label: tt("policyRef"), value: d.policy.ref },
          { label: tt("decisionId"), value: d.policy.id },
          ...(d.reasonCodes.length > 0 ? [{ label: tt("evaluatorCodes"), value: d.reasonCodes.join(", ") }] : []),
          ...(d.policy.reasonCodes.length > 0
            ? [{ label: tt("policyCodes"), value: d.policy.reasonCodes.join(", ") }]
            : []),
        ]}
      />
    </div>
  );
}

function TaskLink({ id }: { id: string }) {
  const { data: task, isPending } = useTask(id);
  const t = useTranslations("run.inspector");
  const { money, dateTime, until } = useFormat();
  const { zone } = useViewerTimeZone();
  if (isPending)
    return (
      <Block title={t("reviewerTask")} glyph="human">
        <Skeleton className="h-20" />
      </Block>
    );
  return (
    <Block title={t("reviewerTask")} glyph="human">
      {task ? (
        <>
          <div className="font-medium">{task.title}</div>
          <KeyValues
            className="mt-1"
            rows={[
              {
                label: t("pay"),
                value: (
                  <span className="tnum">
                    {money(task.pay)} <span className="text-muted">{t("simulatedNote")}</span>
                  </span>
                ),
              },
              {
                label: t("due"),
                value: t("dueLine", { when: dateTime(task.deadline, zone), left: until(task.deadline) }),
              },
            ]}
          />
        </>
      ) : null}
      <Link className="link mt-2 inline-block text-sm" href={`/work/tasks/${id}`}>
        {t("openAsReviewer")}
      </Link>
      <TechnicalDetails className="mt-3" rows={[{ label: t("task"), value: id }]} />
    </Block>
  );
}

export function NodeInspector({ node }: { node: RunNode }) {
  const t = useTranslations("run.inspector");
  const tt = useTranslations("run.technical");
  const { money } = useFormat();
  const { line, note, subtitle } = useCodes();
  const details = subtitle(node);
  const rows = [
    {
      label: t("doneBy"),
      value: (
        <span className="inline-flex items-center gap-2">
          <ActorGlyph actor={node.actor} />
          <ActorLabel actor={node.actor} />
        </span>
      ),
    },
    ...(details ? [{ label: t("details"), value: details }] : []),
    ...(node.attempts ? [{ label: t("attempts"), value: t("attemptsOf", { n: node.attempts }) }] : []),
    ...(node.durationS ? [{ label: t("took"), value: duration(node.durationS) }] : []),
    ...(node.cost ? [{ label: t("cost"), value: <span className="tnum">{money(node.cost)}</span> }] : []),
  ];

  return (
    <div className="space-y-4">
      <div className="flex items-start justify-between gap-3">
        <h3 className="text-base leading-snug font-semibold">{node.label}</h3>
        <NodeStatusPill status={node.status} />
      </div>
      {node.note ? (
        <p className="rounded-md bg-stage px-3 py-2 text-[13px] leading-snug text-grey-700">{note(node.note)}</p>
      ) : null}
      <KeyValues rows={rows} />
      {node.output ? (
        <div>
          <div className="label mb-1">{t("result")}</div>
          <p className="text-sm">{line(node.output)}</p>
        </div>
      ) : null}
      {node.decision ? <DecisionBlocks d={node.decision} /> : null}
      {node.humanTaskId ? <TaskLink id={node.humanTaskId} /> : null}
      {node.toolCalls?.length ? (
        <div>
          <div className="label mb-1.5">{t("toolCalls")}</div>
          <ul className="space-y-2">
            {node.toolCalls.map((call) => (
              <li key={call.id} className="rounded-[10px] border border-rule px-3.5 py-2.5 text-sm">
                <div className="flex items-center justify-between gap-2">
                  <span className="font-medium">{call.app}</span>
                  <Pill tone={TOOL_TONE[call.status]}>{t(`toolStatus.${call.status}`)}</Pill>
                </div>
                <div className="mt-1 text-[13px]">{call.action}</div>
                <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-muted">
                  <span>{t("policyLine", { verdict: t(`policy.${call.policy}`) })}</span>
                  {call.mocked ? <MockTag /> : null}
                </div>
                {call.detail && call.detail !== call.action ? (
                  <div className="mt-1 text-xs text-grey-700">{line(call.detail)}</div>
                ) : null}
                <TechnicalDetails
                  className="mt-2"
                  rows={[
                    { label: tt("capability"), value: call.capability },
                    { label: tt("callId"), value: call.id },
                  ]}
                />
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  );
}
