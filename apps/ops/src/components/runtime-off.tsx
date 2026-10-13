import { ApiError } from "@/lib/api/errors";
import { Section } from "./ui";

/** The API answers definitions and memory reads with 503 RUNTIME_UNAVAILABLE while the local runtime is off. */
export const isRuntimeOff = (error: unknown) => error instanceof ApiError && error.code === "RUNTIME_UNAVAILABLE";

/** The empty state for pages that read the definition registry or memory, shown while the runtime is off. */
export function RuntimeOff({ what }: { what: string }) {
  return (
    <Section className="p-6">
      <h2 className="h-section">{what} need the local runtime (Postgres). See README.</h2>
      <p className="mt-2 max-w-[68ch] text-sm leading-relaxed text-muted">
        Start Postgres and Temporal with <code className="font-mono text-[13px]">docker compose up -d</code> from
        demo-app, then run the API with <code className="font-mono text-[13px]">NM_RUNTIME=temporal</code>. The demo-app
        README has the full steps.
      </p>
    </Section>
  );
}
