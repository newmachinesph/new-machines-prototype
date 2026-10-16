"use client";

import type { UseQueryResult } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import type { ReactNode } from "react";
import { ApiError } from "@/lib/api/errors";
import { useErrorText } from "@/lib/api/use-error-text";
import { Button, Callout } from "./ui";

/**
 * Pending shows the skeleton, errors go to the nearest error.tsx, success renders the data. A 401 keeps the
 * skeleton: the client is already signing out and redirecting, so an error panel would only flash. An optional
 * part of a page passes `inline`: its failure shows in place, with a retry, and the rest of the page stays.
 */
export function QueryState<T>({
  query,
  skeleton,
  inline = false,
  children,
}: {
  query: UseQueryResult<T, unknown>;
  skeleton: ReactNode;
  inline?: boolean;
  children: (data: T) => ReactNode;
}) {
  if (query.isPending) return <>{skeleton}</>;
  // A failed background refetch keeps the data it already has; only a failure with nothing to show is an error.
  const { data } = query;
  if (query.isError && data === undefined) {
    if (query.error instanceof ApiError && query.error.status === 401) return <>{skeleton}</>;
    if (inline) return <InlineError query={query} />;
    throw query.error;
  }
  return <>{children(data as T)}</>;
}

function InlineError({ query }: { query: UseQueryResult<unknown, unknown> }) {
  const t = useTranslations("common");
  const errorText = useErrorText();
  return (
    <div className="px-5 py-4">
      <Callout
        tone="blocked"
        title={t("couldNotLoad")}
        action={
          <Button variant="secondary" onClick={() => void query.refetch()}>
            {t("retry")}
          </Button>
        }
      >
        {errorText(query.error)}
      </Callout>
    </div>
  );
}
