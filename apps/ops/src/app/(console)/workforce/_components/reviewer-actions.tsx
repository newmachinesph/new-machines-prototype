"use client";

import { useState } from "react";
import { focusPageHeading, Select, useToast } from "@/components/base";
import { ConfirmAction } from "@/components/confirm-action";
import { ReadOnly } from "@/components/read-only";
import { Button } from "@/components/ui";
import type { Reviewer } from "@/lib/api/gen/types.gen";
import { useCanWrite, useOpsWorkspace } from "@/lib/queries/ops";
import {
  useApproveReviewer,
  useReinstateReviewer,
  useSetReviewerLevel,
  useSuspendReviewer,
} from "@/lib/queries/workforce";
import { LEVELS, canSetLevel, capitalize } from "./tabs";

const LEVEL_ITEMS = LEVELS.map((l) => ({ value: l, label: capitalize(l) }));

export function LevelAction({ reviewer }: { reviewer: Reviewer }) {
  const toast = useToast();
  const setLevel = useSetReviewerLevel();
  const [level, setLevelValue] = useState<Reviewer["level"]>(reviewer.level);
  return (
    <ConfirmAction
      trigger={
        <Button variant="secondary" aria-label={`Set level for ${reviewer.name}`}>
          Set level
        </Button>
      }
      title={`Set level for ${reviewer.name}`}
      consequence="The level decides which tasks this reviewer is offered. It applies to new tasks straight away."
      confirmLabel="Set level"
      confirmDisabled={!canSetLevel(reviewer.level, level)}
      onOpenChange={(o) => {
        if (o) setLevelValue(reviewer.level);
      }}
      onConfirm={async (reason) => {
        await setLevel.mutateAsync({ path: { reviewer_id: reviewer.id }, body: { level, reason } });
        toast(`${reviewer.name} is now ${level}`);
      }}
    >
      <div className="space-y-1.5">
        <div className="label">Level</div>
        <Select value={level} onValueChange={setLevelValue} items={LEVEL_ITEMS} label="Level" />
      </div>
    </ConfirmAction>
  );
}

/** Row buttons share a label across rows, so each one carries the reviewer's name. */
const named = (action: string, r: Reviewer) => `${action} ${r.name}`;

export function ReviewerActions({ reviewer }: { reviewer: Reviewer }) {
  const canWrite = useCanWrite();
  const live = useOpsWorkspace() === "live";
  const toast = useToast();
  const approve = useApproveReviewer();
  const suspend = useSuspendReviewer();
  const reinstate = useReinstateReviewer();

  // Reviewers are fixtures in the live workspace, and the API refuses to change them there.
  if (live) return null;
  if (!canWrite) {
    const labels = {
      applicant: ["Approve as trainee"],
      active: ["Set level", "Suspend"],
      suspended: ["Reinstate"],
    }[reviewer.status];
    return (
      <div className="flex justify-end gap-2">
        {labels.map((label) => (
          <ReadOnly key={label}>
            <Button
              variant="secondary"
              disabled
              aria-label={`${label}${label === "Set level" ? " for" : ""} ${reviewer.name}`}
            >
              {label}
            </Button>
          </ReadOnly>
        ))}
      </div>
    );
  }
  const path = { reviewer_id: reviewer.id };

  if (reviewer.status === "applicant") {
    return (
      <ConfirmAction
        trigger={
          <Button variant="secondary" aria-label={named("Approve as trainee", reviewer)}>
            Approve as trainee
          </Button>
        }
        title={`Approve ${reviewer.name}?`}
        consequence={`${reviewer.name} joins as a trainee and starts receiving tasks suited to that level.`}
        confirmLabel="Approve as trainee"
        onConfirm={async (reason) => {
          await approve.mutateAsync({ path, body: { reason } });
          toast(`${reviewer.name} approved as trainee`);
          focusPageHeading();
        }}
      />
    );
  }
  if (reviewer.status === "suspended") {
    return (
      <ConfirmAction
        trigger={
          <Button variant="secondary" aria-label={named("Reinstate", reviewer)}>
            Reinstate
          </Button>
        }
        title={`Reinstate ${reviewer.name}?`}
        consequence={`${reviewer.name} can receive tasks again at their current level.`}
        confirmLabel="Reinstate reviewer"
        onConfirm={async (reason) => {
          await reinstate.mutateAsync({ path, body: { reason } });
          toast(`${reviewer.name} reinstated`);
          focusPageHeading();
        }}
      />
    );
  }
  return (
    <div className="flex justify-end gap-2">
      <LevelAction reviewer={reviewer} />
      <ConfirmAction
        trigger={
          <Button variant="danger" aria-label={named("Suspend", reviewer)}>
            Suspend
          </Button>
        }
        title={`Suspend ${reviewer.name}?`}
        consequence={`${reviewer.name} stops receiving tasks. Tasks already claimed return to the queue.`}
        confirmLabel="Suspend reviewer"
        destructive
        onConfirm={async (reason) => {
          await suspend.mutateAsync({ path, body: { reason } });
          toast(`${reviewer.name} suspended`);
          focusPageHeading();
        }}
      />
    </div>
  );
}
