"use client";

import { useTranslations } from "next-intl";
import { ErrorPanel } from "@/components/error-panel";

export default function Error({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  const errors = useTranslations("errors");
  const studio = useTranslations("studio");
  // The Studio's own home, not the business overview: the panel keeps the builder where they were working.
  return (
    <ErrorPanel
      title={errors("pageCouldNotLoad")}
      error={error}
      reset={reset}
      home={{ href: "/studio", label: studio("backToStudio") }}
    />
  );
}
