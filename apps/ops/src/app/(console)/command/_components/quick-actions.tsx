"use client";

import { ReadOnly } from "@/components/read-only";
import { Button, ButtonLink } from "@/components/ui";
import { useCanWrite } from "@/lib/queries/ops";

/**
 * `fixtureOnly`: the action works on demo fixtures only. The live workspace creates orgs at sign-up, and its
 * pack listings and incidents are still samples, so it hides these.
 */
const ACTIONS = [
  { label: "New tenant", href: "/tenants?action=new", variant: "primary", fixtureOnly: true },
  { label: "Review packs", href: "/marketplace?tab=in_review", variant: "secondary", fixtureOnly: true },
  { label: "Declare incident", href: "/health?action=declare", variant: "secondary", fixtureOnly: true },
] as const;

/** Shortcuts into the pages that own each dialog. Support is read-only, so it sees them disabled. */
export function QuickActions({ live = false }: { live?: boolean }) {
  const canWrite = useCanWrite();
  const shown = live ? ACTIONS.filter((a) => !a.fixtureOnly) : ACTIONS;
  return (
    <>
      {shown.map((a) =>
        canWrite ? (
          <ButtonLink key={a.label} href={a.href} variant={a.variant}>
            {a.label}
          </ButtonLink>
        ) : (
          <ReadOnly key={a.label}>
            <Button variant={a.variant} disabled>
              {a.label}
            </Button>
          </ReadOnly>
        ),
      )}
    </>
  );
}
