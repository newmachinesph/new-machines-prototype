"use client";

import { useQueryClient } from "@tanstack/react-query";
import { Button, ButtonLink } from "@/components/ui";
import { errorText } from "@/lib/api/error-text";

export function ErrorPanel({
  title,
  error,
  reset,
  home,
}: {
  title: string;
  error: unknown;
  reset: () => void;
  /** Where the secondary button goes; defaults to the command center. */
  home?: { href: string; label: string };
}) {
  const qc = useQueryClient();
  const target = home ?? { href: "/command", label: "Go to command center" };
  // Failed queries stay failed until reset; refetch them so Retry does not depend on the remount.
  const retry = () => {
    void qc.resetQueries({ predicate: (q) => q.state.status === "error" });
    reset();
  };
  return (
    <div role="alert" className="panel mx-auto mt-10 max-w-xl p-6">
      <h1 className="h-section">{title}</h1>
      <p className="mt-2 text-sm leading-relaxed text-grey-700">{errorText(error)}</p>
      <div className="mt-5 flex gap-2">
        <Button onClick={retry}>Retry</Button>
        <ButtonLink href={target.href} variant="secondary">
          {target.label}
        </ButtonLink>
      </div>
    </div>
  );
}
