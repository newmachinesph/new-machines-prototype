"use client";

import { useTranslations } from "next-intl";
import { ButtonLink } from "@/components/ui";
import { useCanBuild } from "../can-build";

/** The list page's "New agent" action, for owners and admins only; the page itself renders on the server. */
export function NewAgentLink({ variant = "primary" }: { variant?: "primary" | "secondary" }) {
  const t = useTranslations("studioAgents");
  if (!useCanBuild()) return null;
  return (
    <ButtonLink href="/studio/agents/new" variant={variant}>
      {t("new")}
    </ButtonLink>
  );
}
