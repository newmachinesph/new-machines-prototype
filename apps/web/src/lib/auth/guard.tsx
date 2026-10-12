"use client";

import { useRouter } from "next/navigation";
import { type ReactNode, useEffect } from "react";
import { Skeleton } from "@/components/skeleton";
import { signInHref } from "./next-path";
import { useSession } from "./session";

/** Signed-out visitors go to the landing page to sign in, and come back to the page they asked for. */
export function Guard({ children }: { children: ReactNode }) {
  const { status } = useSession();
  const router = useRouter();
  useEffect(() => {
    // window.location rather than useSearchParams, which would need a Suspense boundary in every layout.
    if (status === "signed-out") router.replace(signInHref(window.location.pathname + window.location.search));
  }, [status, router]);
  if (status !== "signed-in") return <Skeleton className="m-6 h-[60vh]" />;
  return <>{children}</>;
}
