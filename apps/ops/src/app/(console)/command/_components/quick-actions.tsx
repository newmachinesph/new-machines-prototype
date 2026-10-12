"use client";

import { ReadOnly } from "@/components/read-only";
import { Button, ButtonLink } from "@/components/ui";
import { useCanWrite } from "@/lib/queries/ops";

const ACTIONS = [
  { label: "New tenant", href: "/tenants?action=new", variant: "primary" },
  { label: "Review packs", href: "/marketplace?tab=in_review", variant: "secondary" },
  { label: "Declare incident", href: "/health?action=declare", variant: "secondary" },
] as const;

/** Shortcuts into the pages that own each dialog. Support is read-only, so it sees them disabled. */
export function QuickActions() {
  const canWrite = useCanWrite();
  return (
    <>
      {ACTIONS.map((a) =>
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
