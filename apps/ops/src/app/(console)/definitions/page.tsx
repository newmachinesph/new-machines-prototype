import type { Metadata } from "next";
import { Suspense } from "react";
import { DefinitionsView } from "./_components/definitions-view";

export const metadata: Metadata = { title: "Definitions" };

export default function DefinitionsPage() {
  return (
    <Suspense>
      <DefinitionsView />
    </Suspense>
  );
}
