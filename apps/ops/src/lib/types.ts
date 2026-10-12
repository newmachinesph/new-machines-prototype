// Types come from the API contract (apps/api, generated into ./api/gen). Aliases keep component imports stable.
export type { Money, OpsMe, OpsRun } from "./api/gen/types.gen";
import type { OpsMe, OpsRun } from "./api/gen/types.gen";

export type OpsRole = OpsMe["role"];
export type RunStatus = OpsRun["status"];
