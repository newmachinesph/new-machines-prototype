"use client";

import { useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import type { PendingInvitation } from "@/lib/api/gen/types.gen";
import { useErrorText } from "@/lib/api/use-error-text";
import { Button, Callout } from "@/components/ui";
import { useMe } from "@/lib/queries/me";
import { useAcceptInvitation, useDeclineInvitation } from "@/lib/queries/workspace";

/** One pending invitation to another workspace, with Accept and Decline. */
function InvitationNotice({ invitation }: { invitation: PendingInvitation }) {
  const t = useTranslations("overview.invitation");
  const tn = useTranslations("nav");
  const errorText = useErrorText();
  const router = useRouter();
  const accept = useAcceptInvitation();
  const decline = useDeclineInvitation();
  const busy = accept.isPending || decline.isPending;
  const vars = { path: { org_id: invitation.orgId } };
  const error = accept.error ?? decline.error;
  return (
    <Callout
      tone="info"
      title={t("title", { org: invitation.orgName, role: tn(`roles.${invitation.role}`) })}
      action={
        <div className="flex gap-2">
          <Button variant="secondary" className="h-8" disabled={busy} onClick={() => decline.mutate(vars)}>
            {t("decline")}
          </Button>
          <Button
            className="h-8"
            disabled={busy}
            // A reviewer's work is in the reviewer portal, not the business workspace. The notice is gone
            // before the mutation settles (accepting resets /v1/me), so wait on the promise, not a callback.
            // A failure shows through `accept.error`.
            onClick={() =>
              void accept.mutateAsync(vars).then(
                () => invitation.role === "reviewer" && router.push("/work"),
                () => undefined,
              )
            }
          >
            {t("accept")}
          </Button>
        </div>
      }
    >
      {error ? <span className="text-blocked">{errorText(error)}</span> : t("detail")}
    </Callout>
  );
}

/** Invitations to other workspaces for the signed-in user's verified email (live workspace only). */
export function InvitationNotices() {
  const invitations = useMe().data?.invitations ?? [];
  if (invitations.length === 0) return null;
  return (
    <div className="space-y-3">
      {invitations.map((i) => (
        <InvitationNotice key={i.orgId} invitation={i} />
      ))}
    </div>
  );
}
