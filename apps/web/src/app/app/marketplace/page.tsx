import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";
import { Suspense } from "react";
import { PackGrid, PackGridSkeleton } from "./pack-grid";

export async function generateMetadata(): Promise<Metadata> {
  return { title: (await getTranslations("nav"))("marketplace") };
}

export default function MarketplacePage() {
  return (
    <Suspense fallback={<PackGridSkeleton />}>
      <PackGrid />
    </Suspense>
  );
}
