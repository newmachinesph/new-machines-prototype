import type { Metadata } from "next";
import { Suspense } from "react";
import { ListingsView } from "./_components/listings-view";

export const metadata: Metadata = { title: "Review queue" };

export default function ListingsPage() {
  return (
    <Suspense>
      <ListingsView />
    </Suspense>
  );
}
