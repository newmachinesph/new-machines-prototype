"use client";

import { focusPageHeading, useToast } from "@/components/base";
import { ConfirmAction } from "@/components/confirm-action";
import { Button } from "@/components/ui";
import { type PackAction, usePackAction } from "@/lib/queries/marketplace";
import { useCanWrite } from "@/lib/queries/ops";
import { type PackStatus, validActions } from "./pack-state";
import { ReadOnly } from "@/components/read-only";

type PackRef = { slug: string; name: string; status: PackStatus; certified: boolean };

type ActionCopy = {
  label: string;
  title: (name: string) => string;
  consequence: (name: string) => string;
  toast: (name: string) => string;
  destructive?: boolean;
  variant: "primary" | "secondary" | "danger";
  placeholder: string;
};

const COPY: Record<PackAction, ActionCopy> = {
  submit: {
    label: "Submit for review",
    title: (n) => `Submit ${n} for review?`,
    consequence: (n) =>
      `${n} moves to In review. It stays hidden from tenants until an operator approves and publishes it.`,
    toast: (n) => `${n} submitted for review`,
    variant: "primary",
    placeholder: "Connectors and passport checked, ready for review",
  },
  approve: {
    label: "Approve and publish",
    title: (n) => `Approve and publish ${n}?`,
    consequence: (n) => `${n} appears in every tenant's marketplace and tenants can install it straight away.`,
    toast: (n) => `${n} published`,
    variant: "primary",
    placeholder: "Passport reviewed, connector access matches the outcome",
  },
  reject: {
    label: "Reject",
    title: (n) => `Reject ${n}?`,
    consequence: (n) =>
      `${n} is rejected and stays hidden from tenants. Your reason becomes the review notes the publisher sees, so say what to fix. They can submit it again.`,
    toast: (n) => `${n} rejected`,
    destructive: true,
    variant: "danger",
    placeholder: "Write access to Stripe is not justified by the outcome",
  },
  deprecate: {
    label: "Deprecate",
    title: (n) => `Deprecate ${n}?`,
    consequence: () =>
      "Tenants who have not installed it stop seeing it in their marketplace. Existing installs keep working.",
    toast: (n) => `${n} deprecated`,
    destructive: true,
    variant: "danger",
    placeholder: "Superseded by a newer pack",
  },
  republish: {
    label: "Republish",
    title: (n) => `Republish ${n}?`,
    consequence: (n) => `${n} returns to every tenant's marketplace.`,
    toast: (n) => `${n} republished`,
    variant: "primary",
    placeholder: "Issue fixed and retested",
  },
  certify: {
    label: "Certify",
    title: (n) => `Certify ${n}?`,
    consequence: (n) => `${n} shows the certified badge to every tenant. Only certify packs whose passport is current.`,
    toast: (n) => `${n} certified`,
    variant: "secondary",
    placeholder: "Passport retested on the current version",
  },
};

/** The moves the state machine allows from the pack's current status, and no others. */
export function PackActions({ pack }: { pack: PackRef }) {
  const canWrite = useCanWrite();
  const toast = useToast();
  const run = usePackAction();
  const actions = validActions(pack.status, pack.certified);

  return (
    <>
      {actions.map((action) => {
        const copy = COPY[action];
        const button = <Button variant={copy.variant}>{copy.label}</Button>;
        if (!canWrite) {
          return (
            <ReadOnly key={action}>
              <Button variant={copy.variant} disabled>
                {copy.label}
              </Button>
            </ReadOnly>
          );
        }
        return (
          <ConfirmAction
            key={action}
            trigger={button}
            title={copy.title(pack.name)}
            consequence={copy.consequence(pack.name)}
            confirmLabel={copy.label}
            destructive={copy.destructive}
            reasonPlaceholder={copy.placeholder}
            onConfirm={async (reason) => {
              await run(action, pack.slug, reason);
              toast(copy.toast(pack.name));
              focusPageHeading();
            }}
          />
        );
      })}
    </>
  );
}
