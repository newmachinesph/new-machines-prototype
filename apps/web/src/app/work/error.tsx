"use client";

import { useTranslations } from "next-intl";
import { ErrorPanel } from "@/components/error-panel";

export default function Error({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  const errors = useTranslations("errors");
  const work = useTranslations("work");
  return (
    <ErrorPanel
      title={errors("pageCouldNotLoad")}
      error={error}
      reset={reset}
      home={{ href: "/work", label: work("backToTasks") }}
    />
  );
}
