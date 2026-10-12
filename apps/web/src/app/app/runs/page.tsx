import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";
import { Suspense } from "react";
import { Skeleton } from "@/components/skeleton";
import { RunsList } from "./runs-list";

export async function generateMetadata(): Promise<Metadata> {
  return { title: (await getTranslations("nav"))("runs") };
}

export default function RunsPage() {
  return (
    <Suspense fallback={<Skeleton className="h-[480px]" />}>
      <RunsList />
    </Suspense>
  );
}
