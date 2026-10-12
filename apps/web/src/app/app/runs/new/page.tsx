import { Suspense } from "react";
import { Skeleton } from "@/components/skeleton";
import { StartRunPage } from "./start-run-page";

export default function NewRunPage() {
  return (
    <Suspense fallback={<Skeleton className="h-72 max-w-2xl" />}>
      <StartRunPage />
    </Suspense>
  );
}
