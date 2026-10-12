import type { Metadata } from "next";
import { Suspense } from "react";
import { ConnectorsView } from "./_components/connectors-view";

export const metadata: Metadata = { title: "Connectors" };

export default function ConnectorsPage() {
  return (
    <Suspense>
      <ConnectorsView />
    </Suspense>
  );
}
