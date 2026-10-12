"use client";

import { useTranslations } from "next-intl";
import { ErrorPanel } from "@/components/error-panel";

export default function Error({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  const t = useTranslations("errors");
  return <ErrorPanel title={t("pageCouldNotLoad")} error={error} reset={reset} />;
}
