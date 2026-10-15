"use client";

import { useTranslations } from "next-intl";
import { ButtonLink } from "@/components/ui";
import { useCanBuild } from "../can-build";

/** The list page's "New pack" action, for owners and admins only; the page itself renders on the server. */
export function NewPackLink({ variant = "primary" }: { variant?: "primary" | "secondary" }) {
  const t = useTranslations("studioPacks");
  if (!useCanBuild()) return null;
  return (
    <ButtonLink href="/studio/packs/new" variant={variant}>
      {t("new")}
    </ButtonLink>
  );
}
