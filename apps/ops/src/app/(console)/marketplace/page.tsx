import type { Metadata } from "next";
import { Suspense } from "react";
import { MarketplaceView } from "./_components/marketplace-view";

export const metadata: Metadata = { title: "Marketplace" };

export default function MarketplacePage() {
  return (
    <Suspense>
      <MarketplaceView />
    </Suspense>
  );
}
