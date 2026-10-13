import { describe, expect, it } from "vitest";
import type { OpsRunDetail } from "@/lib/api/gen/types.gen";
import type { RunStatus } from "@/lib/types";
import { RUN_POLL_MS, runPollInterval } from "./runs";

const detail = (status: RunStatus) => ({ run: { status }, receipt: {} }) as unknown as OpsRunDetail;

describe("runPollInterval", () => {
  it("polls a run that is running, waiting or verifying", () => {
    for (const status of ["RUNNING", "WAITING_FOR_HUMAN", "WAITING_FOR_EVENT", "VERIFYING"] as const) {
      expect(runPollInterval(detail(status))).toBe(RUN_POLL_MS);
    }
  });

  it("stops once the run has finished, and before there is a run", () => {
    for (const status of ["COMPLETED", "FAILED", "CANCELLED", "NEEDS_ATTENTION"] as const) {
      expect(runPollInterval(detail(status))).toBe(false);
    }
    expect(runPollInterval(undefined)).toBe(false);
  });
});
