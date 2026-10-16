"use client";

import { focusPageHeading, useToast } from "@/components/base";
import { ConfirmAction } from "@/components/confirm-action";
import { ReadOnly } from "@/components/read-only";
import { Button } from "@/components/ui";
import { type ListingAction, useListingAction } from "@/lib/queries/listings";
import { useCanWrite } from "@/lib/queries/ops";

type ListingRef = { id: string; name: string; kind: "pack" | "agent"; status: "pending" | "listed" | "unlisted"; inReview: boolean };

type ActionCopy = {
  label: string;
  title: (name: string) => string;
  consequence: (name: string, kind: ListingRef["kind"]) => string;
  toast: (name: string) => string;
  variant: "primary" | "secondary" | "danger";
  destructive?: boolean;
  placeholder: string;
  reasonLabel?: string;
};

const COPY: Record<ListingAction, ActionCopy> = {
  approve: {
    label: "Approve",
    title: (n) => `Approve ${n}?`,
    consequence: (n) => `The version in review becomes the listed version of ${n}. Buyers can add it straight away.`,
    toast: (n) => `${n} approved`,
    variant: "primary",
    placeholder: "Checks passed and the diff matches what the publisher described",
    reasonLabel: "Note for the publisher",
  },
  "request-changes": {
    label: "Request changes",
    title: (n) => `Request changes to ${n}?`,
    consequence: () => "The version goes back to the publisher. Your reason is what they see, so say what to fix.",
    toast: (n) => `Changes requested for ${n}`,
    variant: "secondary",
    placeholder: "The prompt still mentions a customer by name",
  },
  reject: {
    label: "Reject",
    title: (n) => `Reject ${n}?`,
    consequence: () => "The version is rejected. Your reason becomes the note the publisher sees.",
    toast: (n) => `${n} rejected`,
    variant: "danger",
    destructive: true,
    placeholder: "Sandbox run shows the agent acting outside what it describes",
  },
  unlist: {
    label: "Unlist",
    title: (n) => `Unlist ${n}?`,
    consequence: (_n, kind) =>
      kind === "agent"
        ? "New buyers stop seeing it. Packs that use it stop running until it is relisted."
        : "New buyers stop seeing it, and workspaces that added it cannot start new runs of it until it is relisted. Runs already started finish.",
    toast: (n) => `${n} unlisted`,
    variant: "danger",
    destructive: true,
    placeholder: "Reported as unsafe by a buyer",
  },
  relist: {
    label: "Relist",
    title: (n) => `Relist ${n}?`,
    consequence: (n) => `${n} is visible to buyers again.`,
    toast: (n) => `${n} relisted`,
    variant: "primary",
    placeholder: "Issue fixed and checked",
  },
};

/** The moves the listing's state allows, and no others. */
export function listingMoves(l: Pick<ListingRef, "status" | "inReview">): ListingAction[] {
  if (l.inReview) return ["approve", "request-changes", "reject"];
  if (l.status === "listed") return ["unlist"];
  if (l.status === "unlisted") return ["relist"];
  return [];
}

export function ListingActions({ listing }: { listing: ListingRef }) {
  const canWrite = useCanWrite();
  const toast = useToast();
  const { run } = useListingAction();
  const moves = listingMoves(listing);

  if (moves.length === 0) return null;
  if (!canWrite) {
    return (
      <ReadOnly>
        <span className="text-sm text-muted">Review actions are off for support.</span>
      </ReadOnly>
    );
  }

  return (
    <>
      {moves.map((action) => {
        const copy = COPY[action];
        return (
          <ConfirmAction
            key={action}
            trigger={<Button variant={copy.variant}>{copy.label}</Button>}
            title={copy.title(listing.name)}
            consequence={copy.consequence(listing.name, listing.kind)}
            confirmLabel={copy.label}
            destructive={copy.destructive}
            reasonPlaceholder={copy.placeholder}
            reasonLabel={copy.reasonLabel}
            onConfirm={async (reason) => {
              await run(action, listing.id, reason);
              toast(copy.toast(listing.name));
              focusPageHeading();
            }}
          />
        );
      })}
    </>
  );
}
